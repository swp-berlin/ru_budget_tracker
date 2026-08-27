# Dashboard state and reload fixes

This document describes the state, navigation, About-page, and initial-render changes made in
`fix/coupled-dashboard-state-about-reload`.

## User-visible behavior

- English is the default data language when the URL has no `language` parameter. An explicit
  `language=RU` or a later language-button selection still takes precedence.
- Budget, spending type (`ALL` or `MILITARY`), unit, language, and the selected subject node are
  shared between the Treemap and Time Series views.
- After a user changes a shared setting, that current value is carried into the other view. Old
  values in the entry URL cannot be restored accidentally by changing views.
- The view-specific filters remain separate: `viewby` belongs to the Treemap, while `period`
  belongs to Time Series.
- When the Treemap is rebuilt after an `ALL`/`MILITARY` change, the selected subject node remains
  selected if the same node exists in the new result. If it does not exist, the Treemap opens at
  its root.
- A direct Time Series link containing a multi-part `focus` value retains the complete ancestor
  context, not only the final leaf id.

## State and URL lifecycle

The URL initializes the browser-side stores when a dashboard page is entered. From that point on,
the stores are the authoritative state for the active session. Filter callbacks update both their
store and the URL.

The Treemap/Time Series button now builds its destination query from those current store values.
It also keeps unrelated query parameters, removes the source view's page-specific parameter, and
sets the destination view's page-specific parameter:

- Treemap destination: keep/set `viewby`, remove `period`.
- Time Series destination: keep/set `period`, remove `viewby`.

The selected Treemap node is represented in the URL as its ancestor dimension ids followed by its
leaf dimension id (`focus=ancestor,...,leaf`). This makes the selection independent of Plotly's
short, transient node ids.

## Selection remapping

Every Treemap rebuild creates new compact Plotly ids. The implementation therefore compares a
node's stable identity instead of reusing its old graphical id. Stable identity is the pair:

```text
(leaf dimension id, ordered ancestor dimension ids)
```

If an exact identity is present in the rebuilt node map, the corresponding new Plotly id becomes
the selected id. If there is no exact match—most importantly when a subject has no military
spending—the selected id becomes empty and the root is shown. No fuzzy or label-based matching is
used.

## Initial-render race condition

The captured Chrome log and HAR showed that failed reloads did not send the large Treemap callback
request at all. The browser reported that the callback output `treemap-graph.figure` was not in the
current layout. Successful reloads did send that request and received the complete figure. This is
consistent with a Dash Pages timing race: cached assets can change the ordering, but the cache is
not itself the data error.

Both graph pages now contain a small page-readiness store beside their graph output. Each main
graph callback requires that page-local store as an input. Consequently, initial rendering starts
only after Dash Pages has mounted the page and its graph. The same guard is applied to Time Series
because it uses the same page structure. This follows Dash's documented behavior that newly
inserted inputs trigger their callbacks, while a callback with a missing input does not fire; see
the [Dash app lifecycle](https://dash.plotly.com/app-lifecycle) and
[callback gotchas](https://dash.plotly.com/callback-gotchas).

This is intentionally a narrow reliability fix. It does not change data loading, introduce a new
cache layer, or redesign the large Treemap response.

## About page

The visible logo/header block and H1 were removed. The revised supplied copy replaces the previous
content and is structured with:

- H2 headings for the four sections;
- unordered lists and list items for indented material;
- strong elements for emphasized labels;
- the existing CSS unchanged.

The hidden graph placeholders remain because shared cross-page callbacks still reference those
component ids.

## Verification checklist

1. Open `/` without query parameters and confirm that the Treemap labels are English and the
   language button offers `RU`.
2. Open a direct link with explicit filters, switch views twice, and confirm the same shared filter
   values remain active.
3. Change unit, language, or spending type in either view, switch views, and confirm the new value
   is retained.
4. Select a Treemap subject that exists in both `ALL` and `MILITARY`; switch between them and
   confirm the subject remains selected.
5. Select a subject absent from `MILITARY`; switch to `MILITARY` and confirm the root is shown.
6. Select a subject, switch to Time Series and back, and confirm the subject remains selected.
7. Repeatedly reload `/` with Enter, F5, and Ctrl+F5; confirm that a graph request is made and the
   Treemap appears each time.
8. Open `/about` and confirm the new four-section text, links, list indentation, bold labels, and
   absence of the old logo/header block.

The automated regression tests cover URL/store precedence, direct-link ancestor context, semantic
node remapping, and the root fallback. The initial-render check remains a browser-level manual test
because its original failure depended on client-side component-mount timing.
