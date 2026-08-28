# sarana-verify

**Check for yourself that the aid disbursement figures are real.**

This tool recomputes SARANA's aid ledger from published data and tells you whether the
numbers add up. You do not need an account, a password, or anyone's permission. If the
published record has been altered since it was written, this exits with an error and names
the exact payment where the discrepancy starts.

It is written to be checked, not trusted. Everything below is what it does and why that
constitutes proof.

## Running it

You need Python 3.12 or later. Nothing else.

```bash
python verify.py --base-url https://api.sarana.lk
```

Or against files you have already downloaded:

```bash
curl -o ledger.json  https://api.sarana.lk/api/v1/ledger/public
curl -o anchors.json https://api.sarana.lk/api/v1/ledger/anchors

python verify.py --feed ledger.json --anchors anchors.json
```

## Reading the result

A clean ledger:

```
verifying 48,211 ledger entries against 214 published anchors

VERIFIED. Every entry from seq 1 to 48211 hashes to its published value,
the chain is unbroken, and every daily Merkle root matches its anchor.
```

Exit code `0`.

A ledger that has been altered:

```
VERIFICATION FAILED

The hash chain diverges:
  seq 4211: entry_hash does not match the entry's contents - this row has been
            altered since it was written
    expected: 9f2c...
    found:    3a71...
```

Exit code `1`. **Quote that sequence number** when you report it.

Exit code `2` means the tool could not fetch or read the data — that is not a pass. "I
could not check" and "I checked and it is fine" are different answers, and this tool never
confuses them.

## What it actually checks

Two independent things, which fail in different ways.

### 1. The chain

Every payment record carries a hash of its own contents and a hash of the record before
it. The tool recomputes both for every entry:

```
entry_hash = SHA256( canonical_json(entry without its hashes) || prev_hash )
```

`canonical_json` is [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785), a standard way of
writing JSON so that the same data always produces exactly the same bytes. It has to be a
standard: if SARANA and this tool serialised the same payment differently, the hashes
would differ and verification would be meaningless.

"Without its hashes" means without four fields: `prev_hash` and `entry_hash`, because they
are the output; and `seq` and `anchor_date`, because they are storage and grouping
metadata. The chain linkage already fixes the order, so committing to the row number as
well would make an honest renumbering look like tampering. Every entry in the feed carries
those four alongside the fields that *are* hashed, so you can strip them and recompute with
nothing but `sha256sum` and patience.

- **Change a payment amount** → that entry's own hash stops matching.
- **Delete a payment** → every remaining hash is still individually valid, but the *chain*
  between them breaks.

### 2. The daily anchors

The chain alone is not enough, and it is important to be clear about why.

Someone with write access to the database could alter a payment and then recompute every
hash after it. The chain would be internally perfect. This is not a hypothetical — it is
the attack the design has to survive, and there is a test for it.

So every day, SARANA reduces that day's payments to a single Merkle root and writes it to
storage under an **object lock in compliance mode**, retained for seven years. In that
mode the record cannot be altered or deleted by anyone — not an administrator, not the
account owner. The same root is published in the anchor feed.

The tool recomputes each day's root from the published payments and compares it with the
anchored one. **A rewritten chain still fails here**, because yesterday's anchor cannot be
rewritten.

Each anchor also commits to how many entries that day held, so removing the *last* payment
of a day — which leaves a perfectly valid chain — is caught by the count.

The anchors are chained to each other as well. Each one carries `prev_anchor_hash`, the
hash of the previous day's whole record, so removing an *entire day* is as detectable as
altering one row inside it: the day after the deleted one names a predecessor that is no
longer published.

## Why you can trust the tool itself

Fair question. Some things you can check without reading all of it:

- **It has no credentials.** There is a test asserting the source contains no
  authorisation header, no password, and no database driver. It cannot access anything you
  cannot.
- **Its inputs are public.** Both endpoints it reads are unauthenticated. You can fetch
  them yourself, in a browser, and compare.
- **The algorithms are published standards.** RFC 8785 and SHA-256 Merkle trees. If you do
  not want to trust this implementation, write your own — the specification above is
  complete, and the odd-node rule (duplicate the last node) is the one detail
  implementations usually differ on.
- **It is about 200 lines.** Reading it is a realistic afternoon.

## What this does not prove

Being precise about the limits, because a verification tool that overstates itself is
worse than none:

- It proves the published record has **not been altered since it was written**. It does
  not prove the record was correct when written. A payment that was never made, entered
  honestly into the system, hashes perfectly.
- It covers what is **published**. If a payment was never written to the ledger at all,
  there is nothing here to catch it — that is what the grievance process and the
  disbursement gate are for.
- The anchors are only as strong as the object-lock configuration behind them. That
  configuration is part of the infrastructure definition and should be audited separately.

The chain and the anchors together answer one question well: *has anyone quietly changed
the record after the fact?*

## Reporting a discrepancy

If this exits non-zero, save the output and the two JSON files you fetched. The sequence
number identifies the exact payment. Both files are public, so anyone can repeat the check
and get the same answer.
