# Interface conventions

- All current and newly added site text must use Microsoft JhengHei (微軟正黑體).
  Keep the font stack in `.streamlit/config.toml` and `assets/dashboard.css`, loaded centrally by
  `mori/dashboard.py`; include chart/canvas text when adding charts. Preserve
  Material Symbols for icon glyphs only. Do not redistribute proprietary font
  files without an authorized source; devices without the font use the fallback.
- Keep the Mori brand primary color `#17421E`.
- Budget navigation uses real, labelled Streamlit buttons with selected states,
  not bare text tabs. Only render the selected section.
- Project navigation indexes stored project groups dynamically, not platform names.
  Year is a lookup filter; never clip spend windows to the selected calendar year.
  Navigation changes reuse loaded reports and must not trigger new API requests.

# Shared design standard

- Every new screen must use `mori.design_system` and `assets/dashboard.css`, loaded centrally by `mori/dashboard.py`. Preserve the same page header, decision cards, controls, tables, empty states and section spacing; do not introduce a separate visual theme per feature.
- Use forest green #17421E, white surfaces, a quiet neutral canvas and restrained champagne accents. Avoid decorative gradients, large colour banners, nested card borders and tiny low-contrast text.
- Lead with the result and the primary action; show comparisons and charts next. Put configuration in a native popover and long methods/audits in collapsed expanders. Keep errors and stale-data status visible.
- Body text is at least 18px, supporting text 16px and control targets 44px or larger. Use tabular figures; Meta money is integer, Google/combined money keeps a smaller, softer fraction.
- Use real Streamlit controls with visible keyboard focus. Test desktop and narrow layouts when preview is available, using explicitly labelled synthetic data; never insert demo figures into production failures.

- Inject styles with `st.html`, not Markdown concatenations of multiple style blocks. Keep decorative icons out of accessible control names.
