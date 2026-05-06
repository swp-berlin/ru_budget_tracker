window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

Object.assign(window.dash_clientside.clientside, {
  // ---------------------------------------------------------------------------
  // findAndClickSlice
  //
  // Zooms the treemap into the node specified by the URL's ?focus= parameter.
  //
  // Triggered whenever the URL search string or the treemap figure changes —
  // so focus is re-applied after filter changes or language switches.
  //
  // How the focus parameter works:
  //   - The URL stores a numeric dimension_id as the focus value, e.g. ?focus=42.
  //   - nodeMap maps short node ids (used internally by Plotly) to dimension data:
  //       { "7": { leaf: "42", ctx: [parentDimId, ...] }, ... }
  //   - We scan nodeMap to find which short node id corresponds to the dimension,
  //     then tell Plotly to zoom into that node.
  //
  // Focus is only applied when the URL's budget_id and viewby match the current
  // store values. This prevents an old ?focus= from a shared link being applied
  // after the user switches to a different budget or view.
  //
  // @param {string} search          - URL query string, e.g. "?focus=42&budget_id=1&viewby=chapter"
  // @param {object} figure          - The Plotly figure object (also used as a trigger)
  // @param {object} nodeMap         - {short_id: {leaf: dim_id_str, ctx: [...]}}
  // @param {string} language        - Active language ("RU" or "EN")
  // @param {number} currentBudgetId - Budget id currently loaded in the store
  // @param {string} currentViewby   - View-by value currently loaded in the store
  // @returns {string} Status string written to a hidden dummy output element.
  // ---------------------------------------------------------------------------
  findAndClickSlice: function (search, figure, nodeMap, language, currentBudgetId, currentViewby) {
    if (!search) return "no search params";

    const params = new URLSearchParams(search);

    // Skip focus if budget_id or viewby in the URL don't match the current store values.
    // Only block when the store value is actually set — null means not yet initialised,
    // and blocking too early would prevent the focus from ever being applied on page load.
    const urlBudgetId = params.get("budget_id");
    if (urlBudgetId && currentBudgetId != null && String(currentBudgetId) !== String(urlBudgetId)) {
      return "budget mismatch, skipping focus";
    }
    const urlViewby = params.get("viewby");
    if (urlViewby && currentViewby != null && String(currentViewby) !== String(urlViewby)) {
      return "viewby mismatch, skipping focus";
    }

    // Read the ?focus= value from the URL.
    const focusParam = params.get("focus");
    if (!focusParam) return "no focus param";

    let nodeId = decodeURIComponent(focusParam).trim();

    // ?focus= stores a numeric dimension_id (set by copyShareLink).
    // Translate it to the short node id used in the current figure.
    // nodeMap is keyed by short_id; we scan for the entry whose "leaf" matches.
    // The figure only contains ids for the active language, so we also verify
    // that the candidate short_id is actually present in the figure's id list
    // before using it — otherwise we might zoom into a node that isn't rendered.
    const dimId = parseInt(nodeId, 10);
    if (!isNaN(dimId) && nodeMap) {
      const figureIds = figure?.data?.[0]?.ids;
      for (const [shortId, entry] of Object.entries(nodeMap)) {
        if (String(entry?.leaf ?? entry) === String(dimId)) {
          if (!figureIds || figureIds.includes(shortId)) {
            nodeId = shortId;
            console.debug("[Treemap Focus] Resolved dim_id", dimId, "→ node", nodeId);
            break;
          }
        }
      }
    }

    // Skip if the node doesn't exist in the current figure (e.g. wrong filters applied).
    if (figure?.data?.[0]?.ids && !figure.data[0].ids.includes(nodeId)) {
      console.debug("[Treemap Focus] Node", nodeId, "not in current figure, skipping");
      return "node not in figure";
    }

    // Returns the Plotly plot div once it's mounted in the DOM, or null if not yet ready.
    function getPlotDiv() {
      return document.querySelector('#treemap-graph .js-plotly-plot');
    }

    // Zoom the treemap into nodeId using Plotly's restyle API.
    // Plotly treemaps have a "level" property that controls which node is shown
    // as the root of the view — setting it to nodeId drills into that node.
    function focusNode() {
      const plotDiv = getPlotDiv();
      if (!plotDiv || typeof window.Plotly?.restyle !== "function") return false;

      // There is only one treemap trace; find its index to pass to restyle.
      const traceIndex = (plotDiv.data || []).findIndex((t) => t.type === "treemap");
      if (traceIndex < 0) return false;

      try {
        window.Plotly.restyle(plotDiv, { level: nodeId }, [traceIndex]);
        console.debug("[Treemap Focus] Focused node", nodeId);
        return true;
      } catch (e) {
        console.debug("[Treemap Focus] restyle failed", e);
        return false;
      }
    }

    // The Plotly div may not be mounted yet immediately after a figure update,
    // so we poll briefly (up to 5 times, 150 ms apart) before giving up.
    let attempts = 0;
    function poll() {
      attempts++;
      if (focusNode()) return;
      if (attempts < 5) setTimeout(poll, 150);
    }
    setTimeout(poll, 50);

    return `focusing node ${nodeId}`;
  },

  // ---------------------------------------------------------------------------
  // restoreTreemapZoom
  //
  // Restores the treemap zoom level to the previously selected node after a
  // figure update (e.g. filter change, language switch).
  //
  // Without this, every figure update would reset the view to the top level,
  // losing the user's current drill-down position.
  //
  // Uses Plotly.restyle rather than a full figure update so the existing
  // MutationObserver on the treemap layer keeps firing correctly.
  //
  // @param {object}      figure        - Treemap figure (used as trigger only)
  // @param {string|null} selectedNodeId - Node id stored in store-selected-id
  // @returns {window.dash_clientside.no_update}
  // ---------------------------------------------------------------------------
  restoreTreemapZoom: function (figure, selectedNodeId) {
    if (!figure?.data?.length || !selectedNodeId) return window.dash_clientside.no_update;

    const ids = figure.data[0].ids;

    // Only restore if the previously selected node actually exists in the new figure.
    // It may be absent if the user changed a filter that removes that node entirely.
    if (!Array.isArray(ids) || !ids.includes(selectedNodeId)) return window.dash_clientside.no_update;

    // Poll until the Plotly div is ready, then restyle the level.
    function tryRestyle(attempts) {
      const plotDiv = document.querySelector('#treemap-graph .js-plotly-plot');
      if (!plotDiv || typeof window.Plotly?.restyle !== 'function') {
        if (attempts < 10) setTimeout(() => tryRestyle(attempts + 1), 150);
        return;
      }
      window.Plotly.restyle(plotDiv, { level: selectedNodeId }, [0]);
    }

    setTimeout(() => tryRestyle(0), 50);
    return window.dash_clientside.no_update;
  },
});
