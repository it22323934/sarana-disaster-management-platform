/**
 * The media queue.
 *
 * Two rules that lose evidence if they are wrong: an unsent photo is never evicted, and
 * a deferred photo is never forgotten.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { migrate } from '../src/offline/db/schema.js';
import type { Database } from '../src/offline/db/types.js';
import { MediaQueue, type NewMedia } from '../src/offline/media/queue.js';
import { MEDIA_CACHE_LIMIT_BYTES } from '../src/offline/storage/guard.js';
import { CELLULAR, TestClock, WIFI } from '../test-support/fakes.js';
import { openTestDatabase } from '../test-support/node-database.js';

let db: Database;
let clock: TestClock;
let queue: MediaQueue;

beforeEach(async () => {
  db = openTestDatabase();
  await migrate(db);
  clock = new TestClock();
  queue = new MediaQueue(db, clock);
});

afterEach(async () => {
  await db.close();
});

const photo: NewMedia = {
  client_operation_id: 'op-1',
  entity_type: 'assessment',
  entity_local_id: 'asm-1',
  kind: 'photo',
  local_uri: 'file:///data/sarana/photo-1.jpg',
  content_type: 'image/jpeg',
  size_bytes: 1_400_000,
};

describe('enqueue', () => {
  it('keeps the coordinate as a column, not embedded in the file', () => {
    // GPS is lifted out of EXIF and then stripped from the image. The coordinate is
    // evidence and belongs where a reviewer can see it; leaving it in a file that may
    // later be shown to the public is how a household's address leaks.
    return queue
      .enqueue({ ...photo, latitude: 7.2906, longitude: 80.6337 })
      .then(async (item) => {
        expect(item.latitude).toBe(7.2906);
        expect(item.longitude).toBe(80.6337);
        expect((await queue.byId(item.id))?.status).toBe('pending');
      });
  });

  it('refuses a kind the server has no route for', async () => {
    // The CHECK constraint, not application code. A video would presign against nothing.
    await expect(
      db.execute(
        "INSERT INTO media_upload (id, client_operation_id, entity_type, entity_local_id, " +
          "kind, local_uri, content_type, size_bytes, created_at, status) VALUES " +
          "('m1', 'op-1', 'assessment', 'asm-1', 'video', 'file:///v.mp4', 'video/mp4', " +
          "1, '2026-09-08T06:00:00Z', 'pending')",
      ),
    ).rejects.toThrow();
  });
});

describe('claimable', () => {
  it('sends on Wi-Fi', async () => {
    await queue.enqueue(photo);
    expect(await queue.claimable(WIFI)).toHaveLength(1);
  });

  it('defers on a metered link and says so, rather than leaving it looking stuck', async () => {
    const item = await queue.enqueue(photo);
    expect(await queue.claimable(CELLULAR)).toHaveLength(0);
    expect((await queue.byId(item.id))?.status).toBe('deferred');
    expect((await queue.counts()).deferred).toBe(1);
  });

  it('brings a deferred item back the moment Wi-Fi appears', async () => {
    const item = await queue.enqueue(photo);
    await queue.claimable(CELLULAR);
    expect(await queue.claimable(WIFI)).toHaveLength(1);
    expect((await queue.byId(item.id))?.status).toBe('pending');
  });

  it('sends an item the user marked urgent over a metered link', async () => {
    await queue.enqueue({ ...photo, urgent: true });
    expect(await queue.claimable(CELLULAR)).toHaveLength(1);
  });

  it('takes the oldest first', async () => {
    const first = await queue.enqueue(photo);
    clock.advance(60_000);
    await queue.enqueue({ ...photo, client_operation_id: 'op-2' });
    const ready = await queue.claimable(WIFI, 1);
    expect(ready[0]?.id).toBe(first.id);
  });
});

describe('failure handling', () => {
  it('retries a transient failure before calling it failed', async () => {
    const item = await queue.enqueue(photo);
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      await queue.markUploading(item.id);
      await queue.markFailed(item.id, 'timed out');
      expect((await queue.byId(item.id))?.status).toBe('pending');
    }
    await queue.markUploading(item.id);
    await queue.markFailed(item.id, 'timed out');
    expect((await queue.byId(item.id))?.status).toBe('failed');
  });

  it('never retries a refusal', async () => {
    // Too large, or a type the server does not accept. Retrying sends the same file to
    // the same rule.
    const item = await queue.enqueue(photo);
    await queue.markRefused(item.id, 'larger than a photo may be');
    expect(await queue.claimable(WIFI)).toHaveLength(0);
    expect((await queue.counts()).failed).toBe(1);
  });

  it('counts a refusal as needing attention, alongside a failure', async () => {
    // The strip's job is to say how many things need a person, not to teach the user the
    // difference between the two ways a photo can be stuck.
    await queue.markRefused((await queue.enqueue(photo)).id, 'too large');
    const second = await queue.enqueue({ ...photo, client_operation_id: 'op-2' });
    await db.execute("UPDATE media_upload SET status = 'failed' WHERE id = ?", [second.id]);
    expect((await queue.counts()).failed).toBe(2);
  });
});

describe('eviction', () => {
  const big = { ...photo, size_bytes: 300 * 1024 * 1024 };

  it('evicts nothing while under the cap', async () => {
    await queue.enqueue(photo);
    expect((await queue.evict()).removed).toEqual([]);
  });

  it('evicts uploaded media oldest-first when over the cap', async () => {
    const oldest = await queue.enqueue(big);
    await queue.markUploaded(oldest.id, 'key-1');
    clock.advance(60_000);
    const newer = await queue.enqueue({ ...big, client_operation_id: 'op-2' });
    await queue.markUploaded(newer.id, 'key-2');

    const result = await queue.evict(MEDIA_CACHE_LIMIT_BYTES);
    expect(result.removed.map((item) => item.id)).toEqual([oldest.id]);
    expect(result.stillOver).toBe(false);
  });

  it('never evicts a photo that has not reached the server', async () => {
    // The rule the whole function exists for. This is the only copy of evidence attached
    // to a household's damage claim.
    const unsent = await queue.enqueue(big);
    clock.advance(60_000);
    const unsentToo = await queue.enqueue({ ...big, client_operation_id: 'op-2' });

    const result = await queue.evict(MEDIA_CACHE_LIMIT_BYTES);
    expect(result.removed).toEqual([]);
    expect(result.stillOver).toBe(true);
    expect(await queue.byId(unsent.id)).not.toBeNull();
    expect(await queue.byId(unsentToo.id)).not.toBeNull();
  });
});
