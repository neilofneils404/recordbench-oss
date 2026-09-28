# Transcription runtime qualification

The beta candidate uses the versioned
[WhisperX compatibility recipe](../services/transcription/compatibility/README.md).
Source identity, deterministic wheel builds and normal dependency resolution are
separate from acceptance of an actual GPU transcription job.

The September 28, 2026 package audit checked all 153 resolved worker/API
coordinates with no skipped packages. It reported one remaining finding:
`PYSEC-2026-3740` / `GHSA-8mgp-746c-j5xp` in NLTK 3.10.3. Direct CUDA/CPU wheel
versions were mapped to their upstream package versions for advisory lookup;
that audit does not inspect the native binaries or replace an image scan.

The fresh environment installed 155 packages including build tools with a passing
dependency check. Eleven native adapter imports and one-second synthetic audio
decode/resample probes passed with IPv4/IPv6 socket creation denied. No model
constructors or GPU inference ran in those checks.

## NLTK applicability disposition

The affected functions are `TransitionParser.train/parse`,
`AveragedPerceptron.save/load`, `PerceptronTagger.save_to_json` and
`save_maxent_params`. The assessed transcription entry point accepts profile,
language and job options; it does not expose those training/persistence paths.
Its WhisperX alignment call uses the Punkt tokenizer's tabular parameters.

The scoped beta disposition is **affected dependency present; affected
functionality not exposed by the assessed transcription route**. This is not a
claim that NLTK is fixed or that every possible use of it is safe. Retain the
finding in reports and reassess when NLTK/WhisperX, model-import endpoints,
plugin access or training/export capabilities change. Model-independent tests
and synthetic tokenizer probes are bounded evidence, not exhaustive proof for
all inputs. The upstream advisory remains the authority on the affected code.

## Evidence required before the GPU beta claim

- Fresh installation of the API/worker locks with build tools installed first,
  normal dependency checks, and native decoder imports.
- Real reference EN/ES transcription, alignment and Nemotron with the exact
  source/model/image identities and network isolation recorded.
- End-to-end browser playback/export, malformed input, successful retry, restart
  and clean-root recovery of the documented retained state.
- Actual image/OS inventory and advisory dispositions; the package audit above
  does not cover the final base image, OS packages or separate Nemotron image
  contents. The Dockerfile's pinned base still uses distribution package indexes.

Record pending evidence explicitly in the
[reference-install receipt](BETA_REFERENCE_INSTALL.md#acceptance-receipt-and-feedback).
A successful build or import must not be reported as GPU or transcription-quality
acceptance. Additional hardware/model combinations remain unqualified until tested.
