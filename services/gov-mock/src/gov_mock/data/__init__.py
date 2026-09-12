"""Synthetic data generators, seeded by a fixed RNG for reproducibility.

Every generator here is a pure function of `(seed, entity, simulated hour)`. Nothing reads
the wall clock and nothing draws from a shared running stream, so the same scenario at the
same offset produces the same data on every machine, in every test, on every replay of a
demo. That property is what makes `POST /mock/v1/scenario/advance` worth having: a
scenario that produced different rainfall on the second run would be a story, not a test.

Read `gov_mock.data.names` before touching anything that generates a person. The rules
there about what may be generated, and what may never be presented as demographic data,
apply across this package.
"""
