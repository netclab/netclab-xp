// The logo links to extra.homepage, but Material titles it with site_name.
for (const a of document.querySelectorAll("a.md-logo")) {
  a.title = "netclab.dev";
  a.setAttribute("aria-label", "netclab.dev");
}
