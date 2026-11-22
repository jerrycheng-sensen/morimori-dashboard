# Interface conventions

- All current and newly added site text must use Microsoft JhengHei (微軟正黑體).
  Keep the font stack in `.streamlit/config.toml` and the central CSS in
  `mori/dashboard.py`; include chart/canvas text when adding charts. Preserve
  Material Symbols for icon glyphs only. Do not redistribute proprietary font
  files without an authorized source; devices without the font use the fallback.
- Keep the Mori brand primary color `#17421E`.
- Budget navigation uses real, labelled Streamlit buttons with selected states,
  not bare text tabs. Only render the selected section.
- Project navigation indexes stored project groups dynamically, not platform names.
  Year is a lookup filter; never clip spend windows to the selected calendar year.
  Navigation changes reuse loaded reports and must not trigger new API requests.
