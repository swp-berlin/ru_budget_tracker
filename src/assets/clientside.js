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
      // Prefer Plotly's internal restyle API to zoom without relying on DOM events.
      // This matches manual click behavior more closely and avoids missing labels.
      try {
        if (plotDiv && window.Plotly && typeof window.Plotly.restyle === 'function') {
          const plotData = Array.isArray(plotDiv.data) ? plotDiv.data : [];
          let traceIndex = -1;
          for (let i = 0; i < plotData.length; i += 1) {
            const tr = plotData[i];
            if (tr && tr.type === 'treemap' && Array.isArray(tr.ids)) {
              if (tr.ids.includes(targetId)) {
                traceIndex = i;
                break;
              }
            }
          }
          if (traceIndex >= 0) {
            // Use the stable id first; fall back to label if needed.
            const labelFromFig = (figJson && figJson.data && figJson.data[0] && figJson.data[0].labels)
              ? figJson.data[0].labels[idx]
              : null;
            console.debug('[Treemap Focus] Plotly.restyle level', { traceIndex, targetId, labelFromFig });
            window.Plotly.restyle(plotDiv, { level: targetId }, [traceIndex]);
            if (labelFromFig) {
              // Plotly tolerates redundant restyle; this helps if level expects label.
              window.Plotly.restyle(plotDiv, { level: labelFromFig }, [traceIndex]);
            }
            return true;
          }
        }
      } catch (e) {
        console.debug('[Treemap Focus] Plotly.restyle failed', e);
      }
      // Prefer Plotly's internal click API when available to ensure deep-node focus.
      try {
        if (plotDiv && window.Plotly && typeof window.Plotly.Fx?.click === 'function') {
          // Resolve the correct treemap trace and point index inside Plotly's data arrays.
          const plotData = Array.isArray(plotDiv.data) ? plotDiv.data : [];
          let traceIndex = -1;
          let pointNumber = idx;
          for (let i = 0; i < plotData.length; i += 1) {
            const tr = plotData[i];
            if (tr && tr.type === 'treemap' && Array.isArray(tr.ids)) {
              const localIdx = tr.ids.findIndex((id) => id === targetId);
              if (localIdx >= 0) {
                traceIndex = i;
                pointNumber = localIdx;
                break;
              }
            }
          }
          if (traceIndex >= 0) {
            console.debug('[Treemap Focus] Plotly.Fx.click', { traceIndex, pointNumber, targetId });
            window.Plotly.Fx.click(plotDiv, { points: [{ curveNumber: traceIndex, pointNumber }] });
            return true;
          }
        }
      } catch (e) {
        console.debug('[Treemap Focus] Plotly.Fx.click failed', e);
      }
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
      // Use a point well inside the tile to avoid boundary misses or label overlays.
      const bbox = clickable.getBoundingClientRect();
      // Pick a point inside the slice with safe padding so pointer-events resolve to the path.
      const padding = 6; // px
      const cx = Math.min(bbox.right - padding, Math.max(bbox.left + padding, bbox.left + bbox.width / 2));
      const cy = Math.min(bbox.bottom - padding, Math.max(bbox.top + padding, bbox.top + bbox.height / 2));
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
      // Prefer dispatching on the element resolved from the point to align with Plotly's hit-testing.
      const targetForEvents = hitElem || clickable || plotDiv;
      const seq = ['pointerover', 'mouseover', 'pointerenter', 'mouseenter', 'pointermove', 'mousemove', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
      seq.forEach((type) => {
        // Use MouseEvent for compatibility; Plotly listens to mouse events on SVG elements.
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

    /**
     * Check if the treemap is fully rendered by verifying text elements exist.
     * @returns {boolean} True if text elements are present in treemap slices.
     */
    function isTreemapTextRendered() {
      const hostDiv = document.getElementById('treemap-graph');
      if (!hostDiv) return false;
      const plotDiv = hostDiv.querySelector('.js-plotly-plot');
      if (!plotDiv) return false;
      const treemapLayer = plotDiv.querySelector('.treemaplayer');
      if (!treemapLayer) return false;
      // Check for text elements inside slices - these indicate full render
      const textElements = treemapLayer.querySelectorAll('g.slice g.slicetext text');
      const sliceCount = treemapLayer.querySelectorAll('g.slice.cursor-pointer').length;
      // Consider rendered if we have text elements and they're not empty
      if (textElements.length === 0 || sliceCount === 0) return false;
      // Verify at least some text content exists
      let hasText = false;
      textElements.forEach((t) => {
        if (t.textContent && t.textContent.trim().length > 0) hasText = true;
      });
      console.debug('[Treemap Focus] Render check', { textElements: textElements.length, sliceCount, hasText });
      return hasText;
    }

    /**
     * Build an ordered ancestor path from root to target id using trace parents.
     * @param {string} targetId
     * @param {object} figJson
     * @returns {string[]}
     */
    function buildAncestorPath(targetId, figJson) {
      const ids = (figJson && figJson.data && figJson.data[0] && figJson.data[0].ids) || [];
      const parents = (figJson && figJson.data && figJson.data[0] && figJson.data[0].parents) || [];
      const parentMap = new Map();
      for (let i = 0; i < ids.length; i += 1) {
        parentMap.set(ids[i], parents[i]);
      }
      const path = [];
      let current = targetId;
      let guard = 0;
      while (current && guard < 50) {
        path.push(current);
        const next = parentMap.get(current);
        if (!next || next === current) break;
        current = next;
        guard += 1;
      }
      return path.reverse();
    }


    /**
     * Wait for Plotly's plotly_afterplot event to ensure treemap is fully rendered.
     * Falls back to polling if event doesn't fire within timeout.
     * @param {function} callback - Function to call when render is confirmed.
     * @param {number} timeout - Max time to wait in ms (default 5000).
     */
    function waitForPlotlyRender(callback, timeout) {
      timeout = timeout || 5000;
      const hostDiv = document.getElementById('treemap-graph');
      const plotDiv = hostDiv && hostDiv.querySelector('.js-plotly-plot');

      let resolved = false;
      let pollCount = 0;
      const maxPolls = 20; // 20 polls at 250ms = 5s max
      const pollDelay = 250;

      const tryCallback = () => {
        if (resolved) return;
        if (isTreemapTextRendered()) {
          resolved = true;
          console.debug('[Treemap Focus] Treemap fully rendered, proceeding with click');
          // Add small delay after render detection for any final layout adjustments
          setTimeout(callback, 100);
        }
      };

      // Listen for plotly_afterplot event as primary signal
      if (plotDiv) {
        const afterPlotHandler = () => {
          console.debug('[Treemap Focus] plotly_afterplot event received');
          plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
          // Check if text is rendered after the event
          setTimeout(tryCallback, 50);
        };
        plotDiv.addEventListener('plotly_afterplot', afterPlotHandler);
        // Clean up listener after timeout
        setTimeout(() => {
          plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
        }, timeout);
      }

      // Poll as fallback in case event already fired or doesn't fire
      const poll = () => {
        if (resolved) return;
        pollCount++;
        console.debug('[Treemap Focus] Polling for render completion', pollCount);
        if (isTreemapTextRendered()) {
          tryCallback();
          return;
        }
        if (pollCount < maxPolls) {
          setTimeout(poll, pollDelay);
        } else {
          // Give up and try anyway after max polls
          console.debug('[Treemap Focus] Max polls reached, proceeding anyway');
          resolved = true;
          callback();
        }
      };

      // Start polling after initial delay
      setTimeout(poll, 300);
    }

    /**
     * Click through the ancestor path to ensure the final node is visible at maxdepth.
     * This is important when Plotly treemap requires expanding parents to reach deep nodes.
     * Waits for treemap to be fully rendered before clicking.
     * @param {string} targetId
     * @param {object} figJson
     * @returns {boolean}
     */
    function focusSliceByIdSequential(targetId, figJson) {
      if (!figJson || !figJson.data || !figJson.data[0]) return false;
      const hostDiv = document.getElementById('treemap-graph');
      const plotDiv = hostDiv && hostDiv.querySelector('.js-plotly-plot');
      const path = buildAncestorPath(targetId, figJson);
      console.debug('[Treemap Focus] Focusing path', path);

      const stepFocus = (idx) => {
        if (idx >= path.length) return;
        const id = path[idx];
        let didRestyle = false;

        // Prefer Plotly restyle to match manual click behavior per step.
        try {
          if (plotDiv && window.Plotly && typeof window.Plotly.restyle === 'function') {
            const plotData = Array.isArray(plotDiv.data) ? plotDiv.data : [];
            let traceIndex = -1;
            for (let i = 0; i < plotData.length; i += 1) {
              const tr = plotData[i];
              if (tr && tr.type === 'treemap' && Array.isArray(tr.ids) && tr.ids.includes(id)) {
                traceIndex = i;
                break;
              }
            }
            if (traceIndex >= 0) {
              console.debug('[Treemap Focus] Step restyle level', { id, traceIndex, idx });
              window.Plotly.restyle(plotDiv, { level: id }, [traceIndex]);
              didRestyle = true;
            }
          }
        } catch (e) {
          console.debug('[Treemap Focus] Step restyle failed', e);
        }

        if (!didRestyle) {
          const ok = focusSliceById(id, figJson);
          console.debug('[Treemap Focus] Step click result', { id, ok, idx });
        }

        // Wait for Plotly to finish before the next step.
        if (plotDiv) {
          const afterPlotHandler = () => {
            plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
            setTimeout(() => stepFocus(idx + 1), 30);
          };
          plotDiv.addEventListener('plotly_afterplot', afterPlotHandler);
          setTimeout(() => {
            plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
            stepFocus(idx + 1);
          }, 10);
        } else {
          setTimeout(() => stepFocus(idx + 1), 50);
        }
      };

      // Ensure the base treemap is fully rendered before stepping into the path.
      waitForPlotlyRender(() => stepFocus(0));
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
        // Prefer sequential clicks to expand parents before targeting the final node.
        const ok = focusSliceByIdSequential(usedId, figure) || focusSliceById(usedId, figure);
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
  ,
  /**
   * Build a shareable URL from current filters and selected id and copy it.
   * Params included: budget_id, viewby, spending_type, unit, focus
   *
   * @param {number} n_clicks - Button clicks (ignored aside from triggering)
   * @param {string} pathname - Current page path, e.g., '/'
   * @param {number|null} budgetId
   * @param {string} viewby
   * @param {string} spendingType
   * @param {string} unit
   * @param {string|null} selectedId
   * @returns {string} Status message in dummy output title.
   */
  copyShareLink: function (n_clicks, pathname, budgetId, viewby, spendingType, unit, selectedId) {
    try {
      if (!n_clicks) return 'Share not triggered';
      const params = new URLSearchParams();
      if (budgetId != null) params.set('budget_id', String(budgetId));
      if (viewby) params.set('viewby', viewby);
      if (spendingType) params.set('spending_type', spendingType);
      if (unit) params.set('unit', unit);
      if (selectedId) params.set('focus', selectedId);

      const base = window.location.origin + (pathname || '/');
      const url = `${base}?${params.toString()}`;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url);
        return 'Link copied to clipboard';
      }
      // Fallback for older browsers
      const el = document.createElement('textarea');
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      return 'Link copied to clipboard';
    } catch (e) {
      console.debug('[Share] Failed to copy link', e);
      return 'Failed to copy link';
    }
  },

  /**
   * Download the currently rendered Plotly graph as a PNG image.
   * Clientside callback that handles both treemap and timeseries pages.
   * Embeds Google Font for correct rendering in exported image.
   *
   * @param {number} n_clicks - Button clicks (triggers download)
   * @param {string} pathname - Current page pathname
   * @param {number|null} budgetId - Budget ID
   * @param {Array|null} budgetOptions - Budget options array
   * @param {string} unit - Unit label to include in filename
   * @param {string} spendingType - Spending type (for military suffix)
   * @returns {string} Timestamp string for store output
   */
  downloadPlotImage: function (n_clicks, pathname, budgetId, budgetOptions, unit, spendingType) {
    try {
      // If no click, do nothing
      if (!n_clicks) {
        return window.dash_clientside.no_update;
      }

      // Determine which graph to download based on pathname
      var graphId, filenamePrefix;
      if (!pathname || pathname === '/') {
        graphId = 'treemap-graph';
        filenamePrefix = 'treemap';
      } else if (pathname === '/timeseries') {
        graphId = 'timeseries-graph';
        filenamePrefix = 'timeseries';
      } else {
        return window.dash_clientside.no_update;
      }

      // Get the Dash Graph container
      var container = document.getElementById(graphId);
      if (!container) {
        console.warn('[Download] Graph container not found:', graphId);
        return window.dash_clientside.no_update;
      }

      // Find the actual Plotly plot div
      var graphDiv = container.querySelector('.js-plotly-plot');
      if (!graphDiv) {
        graphDiv = container;
      }

      // Verify Plotly data exists
      if (!graphDiv.data || !graphDiv.layout) {
        console.warn('[Download] No Plotly data found on element');
        return window.dash_clientside.no_update;
      }

      // Get budget name from options
      var budgetName = 'unknown';
      if (budgetOptions && budgetId != null) {
        for (var i = 0; i < budgetOptions.length; i++) {
          if (budgetOptions[i].value === budgetId) {
            budgetName = budgetOptions[i].label || 'unknown';
            break;
          }
        }
      }

      // Build filename
      var now = new Date();
      var currentYear = now.getFullYear();
      var timestamp = now.toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      var sanitizedBudget = (budgetName || 'unknown').replace(/\s+/g, '_').replace(/\//g, '-');
      var unitLabel = (unit || 'ABSOLUTE').toLowerCase();
      var militarySuffix = spendingType === 'MILITARY' ? '_military' : '';
      var filename = filenamePrefix + '_' + timestamp + '_' + sanitizedBudget + '_' + unitLabel + militarySuffix;

      // Get dimensions
      var width = graphDiv.offsetWidth || 800;
      var height = graphDiv.offsetHeight || 600;
      var scale = 2;

      // Get the SVG from the current plot
      var svgElement = graphDiv.querySelector('svg.main-svg');
      if (!svgElement) {
        console.warn('[Download] SVG element not found, falling back to Plotly.downloadImage');
        window.Plotly.downloadImage(graphDiv, {
          format: 'png',
          width: width * scale,
          height: height * scale,
          filename: filename
        });
        return now.toISOString();
      }

      // Clone the SVG
      var svgClone = svgElement.cloneNode(true);
      var svgWidth = parseInt(svgElement.getAttribute('width')) || width;
      var svgHeight = parseInt(svgElement.getAttribute('height')) || height;

      // Add a style element with embedded Google Font
      var styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
      styleEl.textContent = '@import url("https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap"); text, tspan { font-family: "Source Sans 3", sans-serif !important; }';
      svgClone.insertBefore(styleEl, svgClone.firstChild);

      // Update all text elements to use Source Sans 3
      var textElements = svgClone.querySelectorAll('text, tspan');
      textElements.forEach(function (el) {
        el.setAttribute('font-family', '"Source Sans 3", sans-serif');
      });

      // Add watermark text element to the SVG
      var watermarkText = 'Stiftung Wissenschaft und Politik (SWP), ' + currentYear + ' | CC BY 4.0';
      var textNS = 'http://www.w3.org/2000/svg';
      var watermark = document.createElementNS(textNS, 'text');
      watermark.setAttribute('x', svgWidth - 10);
      watermark.setAttribute('y', svgHeight - 8);
      watermark.setAttribute('text-anchor', 'end');
      watermark.setAttribute('font-family', '"Source Sans 3", sans-serif');
      watermark.setAttribute('font-size', '12');
      watermark.setAttribute('fill', '#333333');
      watermark.textContent = watermarkText;
      svgClone.appendChild(watermark);

      // Set explicit dimensions
      svgClone.setAttribute('width', svgWidth);
      svgClone.setAttribute('height', svgHeight);
      svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

      // Serialize SVG
      var serializer = new XMLSerializer();
      var svgString = serializer.serializeToString(svgClone);

      // Load the Google Font before drawing
      var fontUrl = 'https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap';

      // Create a hidden element to trigger font loading
      var fontLoader = document.createElement('div');
      fontLoader.style.cssText = 'position:absolute;left:-9999px;font-family:"Source Sans 3",sans-serif;';
      fontLoader.textContent = 'Font loader';
      document.body.appendChild(fontLoader);

      // Wait for font to load, then render
      var fontLoadPromise;
      if (document.fonts && document.fonts.load) {
        fontLoadPromise = document.fonts.load('400 12px "Source Sans 3"').then(function () {
          return document.fonts.load('600 12px "Source Sans 3"');
        });
      } else {
        fontLoadPromise = new Promise(function (resolve) { setTimeout(resolve, 500); });
      }

      fontLoadPromise.then(function () {
        // Create canvas for PNG conversion
        var canvas = document.createElement('canvas');
        canvas.width = svgWidth * scale;
        canvas.height = svgHeight * scale;
        var ctx = canvas.getContext('2d');
        ctx.scale(scale, scale);
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, svgWidth, svgHeight);

        // Create image from SVG
        var img = new Image();
        // Use data URL to avoid CORS issues
        var svgBase64 = btoa(unescape(encodeURIComponent(svgString)));
        var dataUrl = 'data:image/svg+xml;base64,' + svgBase64;

        img.onload = function () {
          ctx.drawImage(img, 0, 0);
          document.body.removeChild(fontLoader);

          // Convert to PNG and download
          canvas.toBlob(function (pngBlob) {
            var downloadUrl = URL.createObjectURL(pngBlob);
            var link = document.createElement('a');
            link.href = downloadUrl;
            link.download = filename + '.png';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(downloadUrl);
            console.debug('[Download] PNG downloaded:', filename);
          }, 'image/png');
        };

        img.onerror = function (err) {
          console.error('[Download] SVG to image failed:', err);
          document.body.removeChild(fontLoader);
          // Fallback to Plotly's built-in export
          window.Plotly.downloadImage(graphDiv, {
            format: 'png',
            width: width * scale,
            height: height * scale,
            filename: filename
          });
        };

        img.src = dataUrl;
      }).catch(function (err) {
        console.error('[Download] Font loading failed:', err);
        document.body.removeChild(fontLoader);
      });

      return now.toISOString();
    } catch (e) {
      console.error('[Download] Error:', e);
      return window.dash_clientside.no_update;
    }
  },

  /**
   * Constrain treemap text to stay within tile boundaries using SVG textLength.
   * Plotly treemap does not clip text — it overflows naturally. This runs after
   * each figure update and compresses any text line wider than (tile - 2*inset).
   *
   * @param {object} figure - Treemap figure (used as trigger only)
   * @returns {window.dash_clientside.no_update}
   */
  applyTreemapTextInset: function (figure) {
    if (!figure || !figure.data || !figure.data.length) return window.dash_clientside.no_update;

    var H_INSET = 5;

    function scheduleInset() {
      var maxTries = 30;
      var tries = 0;

      function tryApply() {
        tries++;
        var plotDiv = document.querySelector('#treemap-graph .js-plotly-plot');
        if (!plotDiv) {
          if (tries < maxTries) setTimeout(tryApply, 100);
          return;
        }

        var slices = plotDiv.querySelectorAll('g.slice');
        var rendered = false;
        slices.forEach(function (slice) {
          var surface = slice.querySelector('path.surface');
          if (surface) {
            try { if (surface.getBBox().width > 0) rendered = true; } catch (e) { }
          }
        });
        if (!rendered) {
          if (tries < maxTries) setTimeout(tryApply, 100);
          return;
        }

        // Re-apply after every navigation. plotly_afterplot fires once per render
        // cycle, right as Plotly *starts* the d3 transition. A 2 s delay ensures
        // the animation has fully settled before re-measuring tile geometry.
        if (!plotDiv._textInsetBound) {
          plotDiv._textInsetBound = true;
          // Plotly fires events via an internal emitter, not DOM CustomEvents, so
          // addEventListener('plotly_restyle') never fires for tile clicks.
          // Use a MutationObserver on the treemap layer's path `d` attributes instead.
          // Plotly rewrites `d` on every re-render; we never touch `d` (only `transform`),
          // so there is no risk of an infinite loop.
          var treemapLayer = plotDiv.querySelector('.treemaplayer');
          if (treemapLayer) {
            var tileObserver = new MutationObserver(function () {
              clearTimeout(plotDiv._textInsetTimer);
              plotDiv._textInsetTimer = setTimeout(scheduleInset, 150);
            });
            tileObserver.observe(treemapLayer, {
              subtree: true,
              attributes: true,
              attributeFilter: ['d'],
            });
            plotDiv._textInsetObserver = tileObserver;
          }
        }

        // Constrain overflowing text by appending scale() to Plotly's SVG transform.
        // Plotly centers g.slicetext at the tile center via translate(tx, ty), so
        // appending scale(ratio, 1) compresses symmetrically around that center.
        // We avoid CSS transforms entirely — they override SVG attribute transforms
        // and cause text to lose its tile-center position.
        slices.forEach(function (slice) {
          var surface = slice.querySelector('path.surface');
          if (!surface) return;
          var gText = slice.querySelector('g.slicetext');
          if (!gText) return;

          // Clear any CSS transforms from previous runs so measurements are clean.
          gText.style.transform = '';
          gText.style.transformOrigin = '';

          // Strip the exact transform string we appended last time (stored in a data
          // attribute) so we always measure against Plotly's unmodified transform.
          // This is robust regardless of what shape our appended string takes.
          var currentTransform = gText.getAttribute('transform') || '';
          var prevAppended = gText.getAttribute('data-text-scale') || '';
          var cleanTransform;
          if (prevAppended && currentTransform.endsWith(prevAppended)) {
            cleanTransform = currentTransform.slice(0, currentTransform.length - prevAppended.length).trim();
          } else {
            // Fallback for first run or mismatched state: strip a bare trailing scale().
            cleanTransform = currentTransform
              .replace(/\s*scale\(\s*[\d.eE+-]+\s*,\s*[\d.eE+-]+\s*\)\s*$/, '')
              .trim();
          }
          gText.setAttribute('transform', cleanTransform);

          var surfaceRect = surface.getBoundingClientRect();
          var textRect = gText.getBoundingClientRect();

          var targetLeft = surfaceRect.left + H_INSET;
          var targetRight = surfaceRect.right - H_INSET;

          // No overflow on either side — nothing to do.
          if (textRect.left >= targetLeft && textRect.right <= targetRight) {
            gText.removeAttribute('data-text-scale');
            return;
          }

          // Anchor the scale to the text's natural left edge (clamped to the left inset
          // boundary). Scaling around this point keeps the left edge visually fixed so
          // compressed text starts at the same relative position as uncompressed text,
          // and only the right edge is pulled inward.
          var anchorVP = Math.max(textRect.left, targetLeft);
          var ratio = (targetRight - anchorVP) / textRect.width;
          if (ratio >= 1 || ratio <= 0) {
            gText.removeAttribute('data-text-scale');
            return;
          }

          // Build a scale transform around the anchor point converted to local SVG
          // coordinates via the CTM.
          var scaleTransform;
          var ctm = gText.getCTM();
          if (ctm && ctm.a !== 0) {
            var localAnchor = (anchorVP - ctm.e) / ctm.a;
            scaleTransform = 'translate(' + localAnchor + ',0) scale(' + ratio + ',1) translate(' + (-localAnchor) + ',0)';
          } else {
            scaleTransform = 'scale(' + ratio + ',1)';
          }

          var appended = (cleanTransform ? ' ' : '') + scaleTransform;
          gText.setAttribute('data-text-scale', appended);
          gText.setAttribute('transform', cleanTransform + appended);
        });
      }

      setTimeout(tryApply, 50);
    }

    scheduleInset();
    return window.dash_clientside.no_update;
  }
};
