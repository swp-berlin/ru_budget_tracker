// Ensure the top-level dash_clientside object exists
window.dash_clientside = window.dash_clientside || {};

// Define the 'clientside' namespace and all its functions
window.dash_clientside.clientside = {
  /**
   * Finds a Plotly treemap node by its label text and simulates a click on it.
   * This function is triggered by a clientside_callback in Dash when URL or figure changes.
   *
   * @param {string} search - The URL search string (query parameters)
   * @param {object} figure - The treemap figure object (used to detect figure updates)
   * @returns {string} A status message for the dummy output component.
   */
  findAndClickSlice: function (search, figure) {
    console.debug('[Treemap Focus] Callback invoked', { search, hasFigure: !!figure });
    // Parse the URL search string to get the focus parameter
    if (!search) {
      return `No search parameters at ${new Date().toISOString()}`;
    }

    // Parse query parameters from URL
    const params = new URLSearchParams(search.replace('?', ''));
    const focusNode = params.get('focus');
    console.debug('[Treemap Focus] Parsed focus param', focusNode);

    // Guard against empty focus parameter
    if (!focusNode) {
      return `No focus parameter found at ${new Date().toISOString()}`;
    }

    // Decode the focus node in case it's URL-encoded
    const decodedFocusNode = decodeURIComponent(focusNode).trim();

    /**
     * Function to find and click the target slice using the specified DOM traversal strategy
     * @param {string} nodeLabel - The text label of the node to find.
     * @returns {boolean} - True if the node was found and clicked, false otherwise.
     */
    // Label-based click removed; only coordinate-based clicks are used.

    /**
     * Try focusing a treemap node using its stable id via Plotly.react.
     * If unavailable, falls back to DOM click simulation by index.
     * @param {string} targetId
     * @param {object} figJson - Plotly figure JSON
     * @returns {boolean}
     */
    function focusSliceById(targetId, figJson) {
      console.debug('[Treemap Focus] Trying synthetic click for id', targetId);
      const hostDiv = document.getElementById('treemap-graph');
      if (!hostDiv || !figJson || !figJson.data || !figJson.data[0]) return false;

      const ids = figJson.data[0].ids || [];
      const idx = ids.findIndex((id) => id === targetId);
      console.debug('[Treemap Focus] ids length / index', ids.length, idx);
      if (idx < 0) return false;

      // Simulate a click on the corresponding DOM slice by index
      const plotDiv = hostDiv.querySelector('.js-plotly-plot');
      // Attach a one-time click listener to confirm event receipt
      if (plotDiv && !plotDiv.__treemapDebugClickAttached) {
        plotDiv.__treemapDebugClickAttached = true;
        plotDiv.addEventListener('click', (ev) => {
          const tgt = ev.target;
          const info = {
            tag: tgt && tgt.tagName,
            classes: tgt && tgt.className,
            x: ev.clientX,
            y: ev.clientY,
          };
          console.debug('[Treemap Focus] Plot container received click', info);
        }, { capture: true });
      }
      const treemapLayer = plotDiv?.querySelector('.treemaplayer');
      // Prefer the treemap trace with the most slices to reduce mismatch across sub-traces
      let traceTreemap = null;
      if (treemapLayer) {
        const traces = treemapLayer.querySelectorAll('.trace.treemap');
        let maxCount = -1;
        traces.forEach((tr) => {
          const count = tr.querySelectorAll('g.slice.cursor-pointer').length;
          if (count > maxCount) { maxCount = count; traceTreemap = tr; }
        });
      }
      if (!traceTreemap) { console.debug('[Treemap Focus] No treemap trace found'); return false; }

      // Prefer selecting by label text from figure at idx, then click by coordinates
      let slice = null;
      {
        try {
          // Normalize labels: remove <br> tags, collapse whitespace, lowercase
          const normalize = (s) => s
            .toString()
            .replace(/<br\s*\/>|<br\s*>|&lt;br\s*&gt;/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .toLowerCase();
          const targetLabel = (figJson && figJson.data && figJson.data[0] && figJson.data[0].labels)
            ? normalize(figJson.data[0].labels[idx] || '')
            : '';
          if (targetLabel) {
            const candidates = traceTreemap.querySelectorAll('g.slice.cursor-pointer');
            // First pass: exact matches only
            let matches = [];
            candidates.forEach((s) => {
              const t = s.querySelector('g.slicetext text');
              const raw = t ? (t.getAttribute('data-unformatted') || t.textContent || '') : '';
              const text = normalize(raw);
              if (text && text === targetLabel) { matches.push(s); }
            });
            // If multiple or none, do includes as secondary
            if (matches.length === 0) {
              candidates.forEach((s) => {
                const t = s.querySelector('g.slicetext text');
                const raw = t ? (t.getAttribute('data-unformatted') || t.textContent || '') : '';
                const text = normalize(raw);
                if (text && text.includes(targetLabel)) { matches.push(s); }
              });
            }
            // Choose the match whose bbox left/top is smallest (closest to origin) to avoid nested duplicates
            if (matches.length > 0) {
              let best = matches[0];
              let bestScore = Infinity;
              matches.forEach((m) => {
                const box = (m.querySelector('path.surface') || m.querySelector('path') || m).getBoundingClientRect();
                const score = box.left + box.top;
                if (score < bestScore) { bestScore = score; best = m; }
              });
              slice = best;
              console.debug('[Treemap Focus] Resolved slice by label match with score', bestScore);
            }
          }
        } catch (_) { }
      }
      // If label resolution failed, try data-point-number
      if (!slice) {
        slice = traceTreemap.querySelector(`g.slice.cursor-pointer[data-point-number="${idx}"]`);
      }
      // Finally, fallback to DOM order
      if (!slice) {
        const allSlices = traceTreemap.querySelectorAll('g.slice.cursor-pointer');
        console.debug('[Treemap Focus] Fallback using DOM order. Total slices:', allSlices.length);
        slice = allSlices[idx] || null;
      }
      if (!slice) { console.debug('[Treemap Focus] No slice for index', idx); return false; }

      const clickable = slice.querySelector('path.surface') || slice.querySelector('path') || slice;
      // Compute click position using the slice's bounding box.
      // Use a point near the top-left inside the tile to avoid hitting nested children.
      const bbox = clickable.getBoundingClientRect();
      // Use small fixed padding from the top-left to avoid nested children,
      // and prevent drifting too far to the right due to width percentages.
      const cx = Math.floor(bbox.left + 1);
      const cy = Math.floor(bbox.top);
      // Ensure the target area is in view
      try { clickable.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (_) { }
      const hitElem = document.elementFromPoint(cx, cy);
      console.debug('[Treemap Focus] elementFromPoint at top hotspot', {
        cx,
        cy,
        hitTag: hitElem && hitElem.tagName,
        hitClass: hitElem && hitElem.className,
      });
      const eventInit = { view: window, bubbles: true, cancelable: true, clientX: cx, clientY: cy, buttons: 1, detail: 1 };
      // Dispatch on the plot div to mimic real user interaction routing
      const targetForEvents = plotDiv || clickable;
      const seq = ['pointerover', 'mouseover', 'pointerenter', 'mouseenter', 'pointermove', 'mousemove', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
      seq.forEach((type) => {
        const evt = new MouseEvent(type, eventInit);
        targetForEvents.dispatchEvent(evt);
      });
      console.debug('[Treemap Focus] Dispatched DOM events to slice index', idx, 'at', { cx, cy, bbox });
      // Temporary highlight for visual confirmation
      try {
        const pathElemHL = slice.querySelector('path.surface') || slice.querySelector('path');
        if (pathElemHL) {
          const prevStroke = pathElemHL.style.stroke;
          const prevWidth = pathElemHL.style.strokeWidth;
          pathElemHL.style.stroke = 'rgb(255,0,0)';
          pathElemHL.style.strokeWidth = '2px';
          setTimeout(() => {
            pathElemHL.style.stroke = prevStroke;
            pathElemHL.style.strokeWidth = prevWidth;
          }, 500);
        }
      } catch (_) { }
      // Also dispatch a synthetic sequence directly on the slice path as a fallback
      try {
        const pathElem = slice.querySelector('path.surface') || slice.querySelector('path');
        if (pathElem) {
          seq.forEach((type) => {
            pathElem.dispatchEvent(new MouseEvent(type, eventInit));
          });
          console.debug('[Treemap Focus] Dispatched direct event sequence on path element');
        }
      } catch (e) {
        console.debug('[Treemap Focus] Error dispatching direct click on path', e);
      }
      return true;
    }

    // Start polling mechanism to find the slice (in case DOM is still loading)
    let attempts = 0;
    const maxAttempts = 5; // Maximum polling attempts
    const pollInterval = 500; // Milliseconds between attempts

    // Use longer initial delay to allow treemap to render
    const initialDelay = 300;

    const pollForSlice = () => {
      attempts++;

      try {
        const idsDebug = (figure && figure.data && figure.data[0] && figure.data[0].ids) || [];
        console.debug('[Treemap Focus] Attempt', attempts, {
          idsCount: Array.isArray(idsDebug) ? idsDebug.length : 0,
          plotlyVersion: (window.Plotly && window.Plotly.version) || 'unknown',
        });
      } catch (_) { }

      // Try to find and click the slice via coordinates only
      const usedIdRaw = (figure && figure.data && figure.data[0] && Array.isArray(figure.data[0].ids))
        ? focusNode // focus parameter may carry id
        : null;
      const usedId = usedIdRaw ? decodeURIComponent(usedIdRaw.replace(/\+/g, ' ')).trim() : null;

      if (usedId) {
        const ok = focusSliceById(usedId, figure);
        console.debug('[Treemap Focus] Synthetic click by id result', ok, 'for id', usedId);
        if (ok) return;
      }

      // Continue polling if not found and under max attempts
      if (attempts < maxAttempts) {
        setTimeout(pollForSlice, pollInterval);
      }
    };

    // Start polling after the calculated initial delay
    console.debug('[Treemap Focus] Starting poll after initial delay', initialDelay);
    setTimeout(pollForSlice, initialDelay);

    // Return a status message for the dummy output component
    const msg = `Search triggered for '${decodedFocusNode}' at ${new Date().toISOString()}`;
    console.debug('[Treemap Focus] Returning status', msg);
    return msg;
  }
};
