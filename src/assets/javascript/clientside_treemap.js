window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

Object.assign(window.dash_clientside.clientside, {
  /**
   * Finds a Plotly treemap node by its id and focuses it.
   * Triggered by a clientside_callback in Dash when URL or figure changes.
   *
   * @param {string} search - The URL search string (query parameters)
   * @param {object} figure - The treemap figure object (used to detect figure updates)
   * @returns {string} A status message for the dummy output component.
   */
  findAndClickSlice: function (search, figure, nodeMap, language) {
    console.debug('[Treemap Focus] Callback invoked', { search, hasFigure: !!figure });

    if (!search) return `No search parameters at ${new Date().toISOString()}`;

    const params = new URLSearchParams(search);
    const focusNode = params.get('focus');
    console.debug('[Treemap Focus] Parsed focus param', focusNode);

    if (!focusNode) return `No focus parameter found at ${new Date().toISOString()}`;

    // URLSearchParams already decodes %xx; apply decodeURIComponent only for double-encoded values.
    let decodedFocusNode = decodeURIComponent(focusNode).trim();

    // If the focus param is a numeric dimension_id, reverse-look it up in the node map.
    // Each entry carries a "language" tag ("RU" or "EN") set during nodeMap construction,
    // so we can reliably select the path that matches the active figure language without
    // relying on Plotly's exact ID format.
    const dimId = parseInt(decodedFocusNode, 10);
    if (!isNaN(dimId) && nodeMap) {
      const currentLang = (language || 'RU').toUpperCase();
      const allEntries = Object.entries(nodeMap).filter(([, info]) => info.dimension_id === dimId);
      // Prefer the entry whose language tag matches the active language; fall back to any match.
      const matchingEntry =
        allEntries.find(([, info]) => info.language === currentLang) || allEntries[0];
      if (matchingEntry) {
        decodedFocusNode = matchingEntry[0];
        console.debug('[Treemap Focus] Resolved dimension_id', dimId, '→', decodedFocusNode, '(lang:', currentLang, ')');
      }
    }

    // If the figure is already loaded and the resolved node is not in it, bail immediately.
    // This avoids 5 × 500 ms retries when the node simply is not present in the current figure.
    if (figure?.data?.[0]?.ids && !figure.data[0].ids.includes(decodedFocusNode)) {
      console.debug('[Treemap Focus] Focus node not in current figure, skipping');
      return `Focus node not in figure at ${new Date().toISOString()}`;
    }

    function getPlotDiv() {
      return document.querySelector('#treemap-graph .js-plotly-plot');
    }

    /**
     * Find the treemap trace containing targetId in plotDiv.data.
     * @returns {{ traceIndex: number, pointNumber: number }}
     */
    function findTreemapTrace(plotDiv, targetId) {
      const plotData = Array.isArray(plotDiv.data) ? plotDiv.data : [];
      for (let i = 0; i < plotData.length; i++) {
        const tr = plotData[i];
        if (tr && tr.type === 'treemap' && Array.isArray(tr.ids)) {
          const pointNumber = tr.ids.findIndex((id) => id === targetId);
          if (pointNumber >= 0) return { traceIndex: i, pointNumber };
        }
      }
      return { traceIndex: -1, pointNumber: -1 };
    }

    function dispatchMouseSequence(target, eventInit) {
      ['pointerover', 'mouseover', 'pointerenter', 'mouseenter', 'pointermove', 'mousemove',
        'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((type) => {
        target.dispatchEvent(new MouseEvent(type, eventInit));
      });
    }

    /**
     * Try focusing a treemap node using Plotly APIs, falling back to DOM click simulation.
     * @param {string} targetId
     * @param {object} figJson - Plotly figure JSON
     * @returns {boolean}
     */
    function focusSliceById(targetId, figJson) {
      console.debug('[Treemap Focus] Trying synthetic click for id', targetId);
      if (!figJson?.data?.[0]) return false;

      const ids = figJson.data[0].ids || [];
      const idx = ids.findIndex((id) => id === targetId);
      console.debug('[Treemap Focus] ids length / index', ids.length, idx);
      if (idx < 0) return false;

      const plotDiv = getPlotDiv();

      // Prefer Plotly's restyle API to zoom without relying on DOM events.
      // This matches manual click behavior more closely and avoids missing labels.
      try {
        if (plotDiv && window.Plotly && typeof window.Plotly.restyle === 'function') {
          const { traceIndex } = findTreemapTrace(plotDiv, targetId);
          if (traceIndex >= 0) {
            const labelFromFig = figJson.data[0].labels?.[idx] ?? null;
            console.debug('[Treemap Focus] Plotly.restyle level', { traceIndex, targetId, labelFromFig });
            window.Plotly.restyle(plotDiv, { level: targetId }, [traceIndex]);
            // Plotly tolerates redundant restyle; this helps if level expects label.
            if (labelFromFig) {
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
          const { traceIndex, pointNumber } = findTreemapTrace(plotDiv, targetId);
          if (traceIndex >= 0) {
            console.debug('[Treemap Focus] Plotly.Fx.click', { traceIndex, pointNumber, targetId });
            window.Plotly.Fx.click(plotDiv, { points: [{ curveNumber: traceIndex, pointNumber }] });
            return true;
          }
        }
      } catch (e) {
        console.debug('[Treemap Focus] Plotly.Fx.click failed', e);
      }

      // Prefer the treemap trace with the most slices to reduce mismatch across sub-traces
      const treemapLayer = plotDiv?.querySelector('.treemaplayer');
      let traceTreemap = null;
      if (treemapLayer) {
        let maxCount = -1;
        treemapLayer.querySelectorAll('.trace.treemap').forEach((tr) => {
          const count = tr.querySelectorAll('g.slice.cursor-pointer').length;
          if (count > maxCount) { maxCount = count; traceTreemap = tr; }
        });
      }
      if (!traceTreemap) { console.debug('[Treemap Focus] No treemap trace found'); return false; }

      // Normalize labels: remove <br> tags, collapse whitespace, lowercase
      const normalize = (s) => s
        .toString()
        .replace(/<br\s*\/>|<br\s*>|&lt;br\s*&gt;/gi, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();

      // Prefer selecting by label text from figure at idx, then click by coordinates
      let slice = null;
      try {
        const targetLabel = figJson.data[0].labels
          ? normalize(figJson.data[0].labels[idx] || '')
          : '';
        if (targetLabel) {
          const candidates = traceTreemap.querySelectorAll('g.slice.cursor-pointer');
          // First pass: exact matches only
          let matches = [];
          candidates.forEach((s) => {
            const t = s.querySelector('g.slicetext text');
            const raw = t ? (t.getAttribute('data-unformatted') || t.textContent || '') : '';
            if (normalize(raw) === targetLabel) matches.push(s);
          });
          // If no exact match, fall back to includes
          if (matches.length === 0) {
            candidates.forEach((s) => {
              const t = s.querySelector('g.slicetext text');
              const raw = t ? (t.getAttribute('data-unformatted') || t.textContent || '') : '';
              const text = normalize(raw);
              if (text && text.includes(targetLabel)) matches.push(s);
            });
          }
          // Choose the match whose bbox left+top is smallest to avoid nested duplicates
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

      // If label resolution failed, try data-point-number
      if (!slice) slice = traceTreemap.querySelector(`g.slice.cursor-pointer[data-point-number="${idx}"]`);
      // Finally, fallback to DOM order
      if (!slice) {
        const allSlices = traceTreemap.querySelectorAll('g.slice.cursor-pointer');
        console.debug('[Treemap Focus] Fallback using DOM order. Total slices:', allSlices.length);
        slice = allSlices[idx] || null;
      }
      if (!slice) { console.debug('[Treemap Focus] No slice for index', idx); return false; }

      const clickable = slice.querySelector('path.surface') || slice.querySelector('path') || slice;
      // Use a point well inside the tile to avoid boundary misses or label overlays.
      const bbox = clickable.getBoundingClientRect();
      const padding = 6;
      const cx = Math.min(bbox.right - padding, Math.max(bbox.left + padding, bbox.left + bbox.width / 2));
      const cy = Math.min(bbox.bottom - padding, Math.max(bbox.top + padding, bbox.top + bbox.height / 2));
      try { clickable.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (_) { }

      const hitElem = document.elementFromPoint(cx, cy);
      console.debug('[Treemap Focus] elementFromPoint at top hotspot', {
        cx, cy,
        hitTag: hitElem?.tagName,
        hitClass: hitElem?.className,
      });

      const eventInit = { view: window, bubbles: true, cancelable: true, clientX: cx, clientY: cy, buttons: 1, detail: 1 };
      // Prefer dispatching on the element resolved from the point to align with Plotly's hit-testing.
      dispatchMouseSequence(hitElem || clickable || plotDiv, eventInit);
      console.debug('[Treemap Focus] Dispatched DOM events to slice index', idx, 'at', { cx, cy, bbox });

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
          dispatchMouseSequence(pathElem, eventInit);
          console.debug('[Treemap Focus] Dispatched direct event sequence on path element');
        }
      } catch (e) {
        console.debug('[Treemap Focus] Error dispatching direct click on path', e);
      }
      return true;
    }

    /**
     * Build an ordered ancestor path from root to target id using trace parents.
     * @param {string} targetId
     * @param {object} figJson
     * @returns {string[]}
     */
    function buildAncestorPath(targetId, figJson) {
      const ids = figJson?.data?.[0]?.ids || [];
      const parents = figJson?.data?.[0]?.parents || [];
      const parentMap = new Map();
      for (let i = 0; i < ids.length; i++) {
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
        guard++;
      }
      return path.reverse();
    }

    /**
     * Wait for Plotly's plotly_afterplot event, then invoke callback.
     * Falls back to a fixed timeout if the event does not fire.
     * @param {function} callback
     * @param {number} timeout - Fallback delay in ms (default 400).
     */
    function waitForPlotlyRender(callback, timeout = 400) {
      const plotDiv = getPlotDiv();
      let resolved = false;
      const resolve = () => {
        if (resolved) return;
        resolved = true;
        if (plotDiv) plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
        setTimeout(callback, 50);
      };
      const afterPlotHandler = () => {
        console.debug('[Treemap Focus] plotly_afterplot received');
        resolve();
      };
      if (plotDiv) plotDiv.addEventListener('plotly_afterplot', afterPlotHandler);
      setTimeout(resolve, timeout);
    }

    /**
     * Click through the ancestor path to ensure the final node is visible at maxdepth.
     * Waits for treemap to be fully rendered before clicking.
     * @param {string} targetId
     * @param {object} figJson
     * @returns {boolean}
     */
    function focusSliceByIdSequential(targetId, figJson) {
      if (!figJson?.data?.[0]) return false;
      const plotDiv = getPlotDiv();
      const path = buildAncestorPath(targetId, figJson);
      console.debug('[Treemap Focus] Focusing path', path);

      const stepFocus = (idx) => {
        if (idx >= path.length) return;
        const id = path[idx];
        let didRestyle = false;

        // Prefer Plotly restyle to match manual click behavior per step.
        try {
          if (plotDiv && window.Plotly && typeof window.Plotly.restyle === 'function') {
            const { traceIndex } = findTreemapTrace(plotDiv, id);
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
          let fallbackTimer = null;
          const afterPlotHandler = () => {
            clearTimeout(fallbackTimer);
            plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
            setTimeout(() => stepFocus(idx + 1), 30);
          };
          plotDiv.addEventListener('plotly_afterplot', afterPlotHandler);
          fallbackTimer = setTimeout(() => {
            plotDiv.removeEventListener('plotly_afterplot', afterPlotHandler);
            stepFocus(idx + 1);
          }, 10);
        } else {
          setTimeout(() => stepFocus(idx + 1), 50);
        }
      };

      waitForPlotlyRender(() => stepFocus(0));
      return true;
    }

    let attempts = 0;

    const pollForSlice = () => {
      attempts++;
      try {
        const idsDebug = figure?.data?.[0]?.ids || [];
        console.debug('[Treemap Focus] Attempt', attempts, {
          idsCount: Array.isArray(idsDebug) ? idsDebug.length : 0,
          plotlyVersion: window.Plotly?.version || 'unknown',
        });
      } catch (_) { }

      if (figure?.data?.[0] && Array.isArray(figure.data[0].ids)) {
        const ok = focusSliceByIdSequential(decodedFocusNode, figure) || focusSliceById(decodedFocusNode, figure);
        console.debug('[Treemap Focus] Synthetic click by id result', ok, 'for id', decodedFocusNode);
        if (ok) return;
      }

      if (attempts < 5) setTimeout(pollForSlice, 500);
    };

    console.debug('[Treemap Focus] Starting poll after initial delay', 300);
    setTimeout(pollForSlice, 300);

    const msg = `Search triggered for '${decodedFocusNode}' at ${new Date().toISOString()}`;
    console.debug('[Treemap Focus] Returning status', msg);
    return msg;
  },

  /**
   * Restore the treemap zoom level to the previously selected node after a figure update.
   * Uses Plotly.restyle so the existing MutationObserver in applyTreemapTextInset keeps firing.
   *
   * @param {object} figure - Treemap figure (trigger only)
   * @param {string|null} selectedNodeId - Node id stored in store-selected-id
   * @returns {window.dash_clientside.no_update}
   */
  restoreTreemapZoom: function (figure, selectedNodeId) {
    if (!figure?.data?.length || !selectedNodeId) return window.dash_clientside.no_update;
    const ids = figure.data[0].ids;
    if (!Array.isArray(ids) || !ids.includes(selectedNodeId)) return window.dash_clientside.no_update;

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

  /**
   * Constrain treemap text to stay within tile boundaries using SVG textLength.
   * Plotly treemap does not clip text — it overflows naturally. This runs after
   * each figure update and compresses any text line wider than (tile - 2*inset).
   *
   * @param {object} figure - Treemap figure (used as trigger only)
   * @returns {window.dash_clientside.no_update}
   */
  applyTreemapTextInset: function (figure) {
    if (!figure?.data?.length) return window.dash_clientside.no_update;

    const THRESHOLD = 1;
    const MARGIN = 5;
    const MIN_FONT_SIZE = 5;

    function applyInsets(plotDiv) {
      plotDiv.querySelectorAll('g.slice').forEach((slice) => {
        if (slice.closest('.pathbar')) return;
        const surface = slice.querySelector('path.surface');
        if (!surface) return;
        const gText = slice.querySelector('g.slicetext');
        if (!gText) return;

        const textEls = gText.querySelectorAll('text');

        // Reset any previous font-size override to get natural measurements.
        textEls.forEach((el) => { el.style.fontSize = ''; });

        const sr = surface.getBoundingClientRect();
        if (sr.width <= 0 || sr.height <= 0) return;

        // Union of all <text> elements in viewport coordinates.
        let tLeft = Infinity, tRight = -Infinity, tTop = Infinity, tBottom = -Infinity;
        textEls.forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) {
            if (r.left   < tLeft)   tLeft   = r.left;
            if (r.right  > tRight)  tRight  = r.right;
            if (r.top    < tTop)    tTop    = r.top;
            if (r.bottom > tBottom) tBottom = r.bottom;
          }
        });
        if (tLeft === Infinity || tRight <= tLeft || tBottom <= tTop) return;

        const halfW = (tRight  - tLeft) / 2;
        const halfH = (tBottom - tTop)  / 2;
        const cx    = tLeft + halfW;
        const cy    = tTop  + halfH;

        // Only scale if text overflows by more than a few pixels (avoids sub-pixel false positives).
        if (tLeft >= sr.left - THRESHOLD && tRight <= sr.right + THRESHOLD && tBottom <= sr.bottom + THRESHOLD) return;

        // Compute ratio to fit with a small margin — only constrain sides that actually overflow.
        let ratio = 1;
        if (tRight  > sr.right)  ratio = Math.min(ratio, (sr.right  - MARGIN - cx) / halfW);
        if (tBottom > sr.bottom) ratio = Math.min(ratio, (sr.bottom - MARGIN - cy) / halfH);

        if (ratio >= 1 || ratio <= 0) return;

        // Reduce font-size proportionally — skip if result would be below minimum readable size.
        textEls.forEach((el) => {
          const sz = parseFloat(window.getComputedStyle(el).fontSize);
          if (sz > 0 && sz * ratio >= MIN_FONT_SIZE) el.style.fontSize = `${sz * ratio}px`;
        });
      });
    }

    let tries = 0;

    function tryApply() {
      tries++;
      const plotDiv = document.querySelector('#treemap-graph .js-plotly-plot');
      if (!plotDiv) {
        if (tries < 30) setTimeout(tryApply, 100);
        return;
      }

      let rendered = false;
      const firstSurface = plotDiv.querySelector('g.slice path.surface');
      if (firstSurface) {
        try { if (firstSurface.getBBox().width > 0) rendered = true; } catch (e) { }
      }
      if (!rendered) {
        if (tries < 30) setTimeout(tryApply, 100);
        return;
      }

      // Reconnect observer only when Plotly has replaced the .treemaplayer element.
      const treemapLayer = plotDiv.querySelector('.treemaplayer');
      if (treemapLayer && plotDiv._observedTreemapLayer !== treemapLayer) {
        if (plotDiv._textInsetObserver) plotDiv._textInsetObserver.disconnect();
        const tileObserver = new MutationObserver(() => {
          clearTimeout(plotDiv._textInsetTimer);
          plotDiv._textInsetTimer = setTimeout(() => applyInsets(plotDiv), 10);
        });
        tileObserver.observe(treemapLayer, {
          subtree: true,
          attributes: true,
          attributeFilter: ['d'],
        });
        plotDiv._textInsetObserver = tileObserver;
        plotDiv._observedTreemapLayer = treemapLayer;
      }

      applyInsets(plotDiv);
    }

    setTimeout(tryApply, 10);
    return window.dash_clientside.no_update;
  },
});
