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
     * Click through the ancestor path to ensure the final node is visible at maxdepth.
     * This is important when Plotly treemap requires expanding parents to reach deep nodes.
     * @param {string} targetId
     * @param {object} figJson
     * @returns {boolean}
     */
    function focusSliceByIdSequential(targetId, figJson) {
      // Single delayed click: wait ~2s for render and then click the target.
      if (!figJson || !figJson.data || !figJson.data[0]) return false;
      console.debug('[Treemap Focus] Single delayed focus for id', targetId);
      setTimeout(() => {
        const ok = focusSliceById(targetId, figJson);
        console.debug('[Treemap Focus] Delayed click result', { id: targetId, ok });
      }, 2000);
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
  }
};
