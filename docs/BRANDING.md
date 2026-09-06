# RecordBench brand assets and project copy

Use these assets and descriptions for the repository, project pages, and
presentations. They describe a development alpha; they do not imply an
institutional endorsement or production acceptance.

## Identity

- **Name:** RecordBench
- **Tagline:** Review the record. Build the work.
- **Positioning:** Local-first discovery and case review for defense teams.
- **Navy:** `#071a3c`
- **Orange:** `#ed4b2f`
- **White:** `#ffffff`

The mark is a white record page over an offset orange folio. Keep its geometry,
colors, and proportions intact. Give it clear space and use a solid background
with enough contrast. The tagline matches the application's sign-in screen.

## Assets

| Asset | Use |
| --- | --- |
| [Record mark](../src/case_intelligence/static/favicon.svg) | Canonical application icon and standalone mark. |
| [Repository banner](assets/recordbench-banner.svg) | Wide wordmark and tagline for the README or a project introduction. |
| [Video teaser](assets/recordbench-teaser.mp4) | Approved 51-second, 1080p glimpse of selected workflows using synthetic records and a maintainer-supplied original soundtrack. Not a full walkthrough. |
| [Teaser preview](assets/recordbench-teaser-preview.jpg) | Linked preview image for surfaces that do not support inline video. |

Both SVGs are self-contained. They contain no external image or font requests,
case screenshots, or deployment details. The banner repeats the canonical
mark's paths at a larger scale; keep them synchronized if the mark changes.
Use descriptive alternative text when embedding either asset.

## Video teaser

Present the video as **RecordBench in 51 seconds**: a quick glimpse of selected
workflows, not a comprehensive tour or tutorial. Pair it with a short invitation
to try synthetic material or contribute workflow feedback. Do not imply that
this preview establishes production readiness or institutional endorsement.

The MP4 includes music but no narration. Keep the on-screen labels visible.
For GitHub, upload the video as an attachment and place its stable
`github.com/user-attachments/assets/` URL alone in a paragraph to render a
player. A repository-file link is only a download fallback, not an inline
player. Keep that fallback for other Markdown viewers. GitHub initializes the
player muted; viewers can unmute it. Never commit the temporary signed media
URL returned by the renderer. Private attachments require repository access.
The approved edit is 51 seconds at 1920 × 1080. Preserve its soundtrack's pitch
and tempo when reusing it.

The maintainer supplied the original soundtrack for this teaser. Inclusion in
this repository does not relicense that music under Apache-2.0 or grant a
standalone music license. Obtain the maintainer's permission for other music
uses. See [media rights](assets/MEDIA_RIGHTS.md).

## Short description

Local-first discovery and case review for defense teams. Search records,
review media, organize findings, and build work product. Development alpha.

## Project introduction

Discovery arrives in folders. Understanding a case takes more.

RecordBench is a self-hosted workspace being built for the work of federal
criminal defense. It brings documents, images, email, spreadsheets, audio,
and video into one place to search, review, ask questions, and develop work
product with the source material close at hand. Its bundled AI workflows use
local models on infrastructure the operator controls.

The aim is practical: help attorneys, investigators, and support staff turn
unorganized discovery into a clearer understanding of the case.

## Maintainer introduction

I'm building RecordBench to help defense teams get more out of discovery.
The goal is to bring scattered records, source-linked review, and useful work
product into one workspace that an office can run itself. It's early, and I'm
looking for people who can help test it with synthetic material, improve the
workflows, and make it easier for another office to get started.

## Keep claims specific

Describe the current alpha's implemented workflows separately from its
long-term direction. The [README](../README.md) carries both. Durable matters,
complete reopenable case packages, Relativity-style load file interchange,
and matter-controlled frontier AI are development goals.

Describe answers, transcripts, and source screening as review aids. Avoid
claims of exhaustive review, guaranteed accuracy, validated confidentiality,
turnkey installation, or complete exports. Hardware figures are evaluation
targets until the required acceptance evidence exists.

Use only synthetic demonstrations. Follow the
[publication checklist](PUBLICATION_CHECKLIST.md) before distributing assets
or changing repository visibility.
