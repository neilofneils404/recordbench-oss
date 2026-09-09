# Matter workspace layout

Matter pages share a full-width outer shell and the same content gutter.
Review, Work product, Case notes, and the other matter tools keep their header
and navigation aligned when moving between pages. Reading cards may still use
an inner reading width. `static/workspace-layout.css` owns this shared geometry;
feature styles own the content inside it.

Long right-hand content must not make left-hand controls unreachable:

- The fixed global matter rail scrolls its list independently, keeping its
  creation, search, and collapse controls available.
- On desktop, Saved conversations stays within Review's scrolling pane. Its
  list scrolls independently and reserves the actual height of the sticky
  question composer, including when that composer grows.
- Desktop Case note tools stay below the fixed header and have their own
  viewport-limited scroll area. On narrow screens they return to normal page
  flow above the saved notes.
- Scroll regions are keyboard reachable; scrolling a sidebar does not move
  the adjacent long content.

Run the bounded synthetic browser acceptance with a matching Chrome and driver:

```console
python scripts/browser-accept-workspace-layout.py \
  --chrome-binary /path/to/chrome \
  --chromedriver /path/to/chromedriver \
  --output /tmp/recordbench-layout-acceptance
```

The script uses temporary invented matters, conversations and notes, an
unavailable generator, and an explicit synthetic storage policy. It clears
inherited RecordBench service settings. It checks alignment at 1800×1000,
1440×480 and 390×844, then uses native wheel events and keyboard navigation to
verify independent scrolling beside long content. The output contains local
screenshots and a receipt identifying the tested commit and working-tree state.
