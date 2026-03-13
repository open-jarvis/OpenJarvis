(function () {
  "use strict";

  var cfg = window.__DOCSEARCH_CONFIG__;
  if (!cfg || !cfg.appId || !cfg.apiKey || !cfg.indexName) return;

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (!header) return;

    var container = document.createElement("div");
    container.id = "docsearch";

    var nativeSearch = header.querySelector(".md-search");
    if (nativeSearch) {
      header.insertBefore(container, nativeSearch);
      nativeSearch.style.display = "none";
    } else {
      header.appendChild(container);
    }

    docsearch({
      appId: cfg.appId,
      apiKey: cfg.apiKey,
      indexName: cfg.indexName,
      container: "#docsearch",
      placeholder: "Search docs...",
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
