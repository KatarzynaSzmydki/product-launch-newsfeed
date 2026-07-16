# Issue #19: close button (X) on the brief detail pane is partially hidden

https://github.com/KatarzynaSzmydki/product-launch-newsfeed/issues/19

## Problem

Reporter: "close button (X) at the top of the brief page is partially hidden - I think you
need to fix it"

In `app.py`, the brief detail pane's header row splits into a `st.columns([5, 1])` layout, with
the "✕" close button placed alone in the narrow 1-unit-wide column (`app.py:363-369`):

```python
header_col, close_col = st.columns([5, 1])
with header_col:
    st.subheader(f"{selected_ticker} · {ticker_to_name.get(selected_ticker, selected_ticker)}")
with close_col:
    if st.button("✕", key="close_detail"):
        st.session_state.pop("selected_ticker", None)
        st.rerun()
```

At narrower viewport widths (the right pane is itself one of a multi-column top-level layout,
so its effective width is already reduced), a 1/6-width column can be too narrow to render a
full-size Streamlit button without clipping its edge — matching the reported symptom.

## Assessment

Straightforward UI/layout bug, not a scope conflict — doesn't touch forecasting, causal claims,
or the disclaimer (§2 non-goals). Not a duplicate of any other open or recently-closed feedback
issue (#4/#6/#13 were about the feedback form section, not the brief detail pane). Feasible
within the existing Streamlit layout with no architecture change.

## Proposed approach

Give the close button more breathing room and/or make it visually robust to a narrow column:
- Widen the ratio (e.g. `st.columns([6, 1])` -> adjust, or a fixed-width small column via
  `st.columns([1, 0.15])`-style ratio tuned against the app's actual rendered width) so the
  button's box isn't squeezed against the pane edge.
- Alternatively/additionally, wrap the button in a `st.container()` with `use_container_width=True`
  removed (already the case) and confirm no custom CSS (`st.markdown(..., unsafe_allow_html=True)`
  elsewhere in `app.py`) is clipping it via `overflow: hidden` on a parent.
- Verify visually with `streamlit run app.py` at both a typical desktop width and a narrower
  browser width, since the report doesn't specify a screen size.

## Affected files

- `app.py` (lines ~363-369, the brief detail pane header)
