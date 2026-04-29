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
    console.debug("[Treemap Focus] Callback invoked", {
      search,
      hasFigure: !!figure,
    });

    if (!search) return `No search parameters at ${new Date().toISOString()}`;

    const params = new URLSearchParams(search);
    const focusNode = params.get("focus");
    console.debug("[Treemap Focus] Parsed focus param", focusNode);

    if (!focusNode)
      return `No focus parameter found at ${new Date().toISOString()}`;

    // URLSearchParams already decodes %xx; apply decodeURIComponent only for double-encoded values.
    let decodedFocusNode = decodeURIComponent(focusNode).trim();

    // If the focus param is a numeric dimension_id, reverse-look it up in the node map.
    // Each entry carries a "language" tag ("RU" or "EN") set during nodeMap construction,
    // so we can reliably select the path that matches the active figure language without
    // relying on Plotly's exact ID format.
    const dimId = parseInt(decodedFocusNode, 10);
    if (!isNaN(dimId) && nodeMap) {
      // Compact nodeMap is keyed by dim_id string: {ru: path, en: path}.
      const currentLang = (language || "RU").toUpperCase();
      const entry = nodeMap[String(dimId)];
      if (entry) {
        decodedFocusNode =
          currentLang === "EN" ? entry.en || entry.ru : entry.ru || entry.en;
        console.debug(
          "[Treemap Focus] Resolved dimension_id",
          dimId,
          "→",
          decodedFocusNode,
          "(lang:",
          currentLang,
          ")"
        );
      }
    }

    // If the figure is already loaded and the resolved node is not in it, bail immediately.
    // This avoids 5 × 500 ms retries when the node simply is not present in the current figure.
    if (
      figure?.data?.[0]?.ids &&
      !figure.data[0].ids.includes(decodedFocusNode)
    ) {
      console.debug(
        "[Treemap Focus] Focus node not in current figure, skipping"
      );
      return `Focus node not in figure at ${new Date().toISOString()}`;
    }

    function getPlotDiv() {
      return document.querySelector("#treemap-graph .js-plotly-plot");
    }

    /**
     * Find the treemap trace containing targetId in plotDiv.data.
     * @returns {{ traceIndex: number, pointNumber: number }}
     */
    function findTreemapTrace(plotDiv, targetId) {
      const plotData = Array.isArray(plotDiv.data) ? plotDiv.data : [];
      for (let i = 0; i < plotData.length; i++) {
        const tr = plotData[i];
        if (tr && tr.type === "treemap" && Array.isArray(tr.ids)) {
          const pointNumber = tr.ids.findIndex((id) => id === targetId);
          if (pointNumber >= 0) return { traceIndex: i, pointNumber };
        }
      }
      return { traceIndex: -1, pointNumber: -1 };
    }

    function dispatchMouseSequence(target, eventInit) {
      [
        "pointerover",
        "mouseover",
        "pointerenter",
        "mouseenter",
        "pointermove",
        "mousemove",
        "pointerdown",
        "mousedown",
        "pointerup",
        "mouseup",
        "click",
      ].forEach((type) => {
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
      console.debug("[Treemap Focus] Trying synthetic click for id", targetId);
      if (!figJson?.data?.[0]) return false;

      const ids = figJson.data[0].ids || [];
      const idx = ids.findIndex((id) => id === targetId);
      console.debug("[Treemap Focus] ids length / index", ids.length, idx);
      if (idx < 0) return false;

      const plotDiv = getPlotDiv();

      // Prefer Plotly's restyle API to zoom without relying on DOM events.
      // This matches manual click behavior more closely and avoids missing labels.
      try {
        if (
          plotDiv &&
          window.Plotly &&
          typeof window.Plotly.restyle === "function"
        ) {
          const { traceIndex } = findTreemapTrace(plotDiv, targetId);
          if (traceIndex >= 0) {
            const labelFromFig = figJson.data[0].labels?.[idx] ?? null;
            console.debug("[Treemap Focus] Plotly.restyle level", {
              traceIndex,
              targetId,
              labelFromFig,
            });
            window.Plotly.restyle(plotDiv, { level: targetId }, [traceIndex]);
            // Plotly tolerates redundant restyle; this helps if level expects label.
            if (labelFromFig) {
              window.Plotly.restyle(plotDiv, { level: labelFromFig }, [
                traceIndex,
              ]);
            }
            return true;
          }
        }
      } catch (e) {
        console.debug("[Treemap Focus] Plotly.restyle failed", e);
      }

      // Prefer Plotly's internal click API when available to ensure deep-node focus.
      try {
        if (
          plotDiv &&
          window.Plotly &&
          typeof window.Plotly.Fx?.click === "function"
        ) {
          const { traceIndex, pointNumber } = findTreemapTrace(
            plotDiv,
            targetId
          );
          if (traceIndex >= 0) {
            console.debug("[Treemap Focus] Plotly.Fx.click", {
              traceIndex,
              pointNumber,
              targetId,
            });
            window.Plotly.Fx.click(plotDiv, {
              points: [{ curveNumber: traceIndex, pointNumber }],
            });
            return true;
          }
        }
      } catch (e) {
        console.debug("[Treemap Focus] Plotly.Fx.click failed", e);
      }

      // Prefer the treemap trace with the most slices to reduce mismatch across sub-traces
      const treemapLayer = plotDiv?.querySelector(".treemaplayer");
      let traceTreemap = null;
      if (treemapLayer) {
        let maxCount = -1;
        treemapLayer.querySelectorAll(".trace.treemap").forEach((tr) => {
          const count = tr.querySelectorAll("g.slice.cursor-pointer").length;
          if (count > maxCount) {
            maxCount = count;
            traceTreemap = tr;
          }
        });
      }
      if (!traceTreemap) {
        console.debug("[Treemap Focus] No treemap trace found");
        return false;
      }

      // Normalize labels: remove <br> tags, collapse whitespace, lowercase
      const normalize = (s) =>
        s
          .toString()
          .replace(/<br\s*\/>|<br\s*>|&lt;br\s*&gt;/gi, " ")
          .replace(/\s+/g, " ")
          .trim()
          .toLowerCase();

      // Prefer selecting by label text from figure at idx, then click by coordinates
      let slice = null;
      try {
        const targetLabel = figJson.data[0].labels
          ? normalize(figJson.data[0].labels[idx] || "")
          : "";
        if (targetLabel) {
          const candidates = traceTreemap.querySelectorAll(
            "g.slice.cursor-pointer"
          );
          // First pass: exact matches only
          let matches = [];
          candidates.forEach((s) => {
            const t = s.querySelector("g.slicetext text");
            const raw = t
              ? t.getAttribute("data-unformatted") || t.textContent || ""
              : "";
            if (normalize(raw) === targetLabel) matches.push(s);
          });
          // If no exact match, fall back to includes
          if (matches.length === 0) {
            candidates.forEach((s) => {
              const t = s.querySelector("g.slicetext text");
              const raw = t
                ? t.getAttribute("data-unformatted") || t.textContent || ""
                : "";
              const text = normalize(raw);
              if (text && text.includes(targetLabel)) matches.push(s);
            });
          }
          // Choose the match whose bbox left+top is smallest to avoid nested duplicates
          if (matches.length > 0) {
            let best = matches[0];
            let bestScore = Infinity;
            matches.forEach((m) => {
              const box = (
                m.querySelector("path.surface") ||
                m.querySelector("path") ||
                m
              ).getBoundingClientRect();
              const score = box.left + box.top;
              if (score < bestScore) {
                bestScore = score;
                best = m;
              }
            });
            slice = best;
            console.debug(
              "[Treemap Focus] Resolved slice by label match with score",
              bestScore
            );
          }
        }
      } catch (_) {}

      // If label resolution failed, try data-point-number
      if (!slice)
        slice = traceTreemap.querySelector(
          `g.slice.cursor-pointer[data-point-number="${idx}"]`
        );
      // Finally, fallback to DOM order
      if (!slice) {
        const allSlices = traceTreemap.querySelectorAll(
          "g.slice.cursor-pointer"
        );
        console.debug(
          "[Treemap Focus] Fallback using DOM order. Total slices:",
          allSlices.length
        );
        slice = allSlices[idx] || null;
      }
      if (!slice) {
        console.debug("[Treemap Focus] No slice for index", idx);
        return false;
      }

      const clickable =
        slice.querySelector("path.surface") ||
        slice.querySelector("path") ||
        slice;
      // Use a point well inside the tile to avoid boundary misses or label overlays.
      const bbox = clickable.getBoundingClientRect();
      const padding = 6;
      const cx = Math.min(
        bbox.right - padding,
        Math.max(bbox.left + padding, bbox.left + bbox.width / 2)
      );
      const cy = Math.min(
        bbox.bottom - padding,
        Math.max(bbox.top + padding, bbox.top + bbox.height / 2)
      );
      try {
        clickable.scrollIntoView({ block: "nearest", inline: "nearest" });
      } catch (_) {}

      const hitElem = document.elementFromPoint(cx, cy);
      console.debug("[Treemap Focus] elementFromPoint at top hotspot", {
        cx,
        cy,
        hitTag: hitElem?.tagName,
        hitClass: hitElem?.className,
      });

      const eventInit = {
        view: window,
        bubbles: true,
        cancelable: true,
        clientX: cx,
        clientY: cy,
        buttons: 1,
        detail: 1,
      };
      // Prefer dispatching on the element resolved from the point to align with Plotly's hit-testing.
      dispatchMouseSequence(hitElem || clickable || plotDiv, eventInit);
      console.debug(
        "[Treemap Focus] Dispatched DOM events to slice index",
        idx,
        "at",
        { cx, cy, bbox }
      );

      try {
        const pathElemHL =
          slice.querySelector("path.surface") || slice.querySelector("path");
        if (pathElemHL) {
          const prevStroke = pathElemHL.style.stroke;
          const prevWidth = pathElemHL.style.strokeWidth;
          pathElemHL.style.stroke = "rgb(255,0,0)";
          pathElemHL.style.strokeWidth = "2px";
          setTimeout(() => {
            pathElemHL.style.stroke = prevStroke;
            pathElemHL.style.strokeWidth = prevWidth;
          }, 500);
        }
      } catch (_) {}

      // Also dispatch a synthetic sequence directly on the slice path as a fallback
      try {
        const pathElem =
          slice.querySelector("path.surface") || slice.querySelector("path");
        if (pathElem) {
          dispatchMouseSequence(pathElem, eventInit);
          console.debug(
            "[Treemap Focus] Dispatched direct event sequence on path element"
          );
        }
      } catch (e) {
        console.debug(
          "[Treemap Focus] Error dispatching direct click on path",
          e
        );
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
    function waitForPlotlyRender(callback, timeout = 150) {
      const plotDiv = getPlotDiv();
      let resolved = false;
      const resolve = () => {
        if (resolved) return;
        resolved = true;
        if (plotDiv)
          plotDiv.removeEventListener("plotly_afterplot", afterPlotHandler);
        setTimeout(callback, 50);
      };
      const afterPlotHandler = () => {
        console.debug("[Treemap Focus] plotly_afterplot received");
        resolve();
      };
      if (plotDiv)
        plotDiv.addEventListener("plotly_afterplot", afterPlotHandler);
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
      console.debug("[Treemap Focus] Focusing path", path);

      const stepFocus = (idx) => {
        if (idx >= path.length) return;
        const id = path[idx];
        let didRestyle = false;

        // Prefer Plotly restyle to match manual click behavior per step.
        try {
          if (
            plotDiv &&
            window.Plotly &&
            typeof window.Plotly.restyle === "function"
          ) {
            const { traceIndex } = findTreemapTrace(plotDiv, id);
            if (traceIndex >= 0) {
              console.debug("[Treemap Focus] Step restyle level", {
                id,
                traceIndex,
                idx,
              });
              window.Plotly.restyle(plotDiv, { level: id }, [traceIndex]);
              didRestyle = true;
            }
          }
        } catch (e) {
          console.debug("[Treemap Focus] Step restyle failed", e);
        }

        if (!didRestyle) {
          const ok = focusSliceById(id, figJson);
          console.debug("[Treemap Focus] Step click result", { id, ok, idx });
        }

        // Wait for Plotly to finish before the next step.
        if (plotDiv) {
          let fallbackTimer = null;
          const afterPlotHandler = () => {
            clearTimeout(fallbackTimer);
            plotDiv.removeEventListener("plotly_afterplot", afterPlotHandler);
            setTimeout(() => stepFocus(idx + 1), 30);
          };
          plotDiv.addEventListener("plotly_afterplot", afterPlotHandler);
          fallbackTimer = setTimeout(() => {
            plotDiv.removeEventListener("plotly_afterplot", afterPlotHandler);
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
        console.debug("[Treemap Focus] Attempt", attempts, {
          idsCount: Array.isArray(idsDebug) ? idsDebug.length : 0,
          plotlyVersion: window.Plotly?.version || "unknown",
        });
      } catch (_) {}

      if (figure?.data?.[0] && Array.isArray(figure.data[0].ids)) {
        const ok =
          focusSliceByIdSequential(decodedFocusNode, figure) ||
          focusSliceById(decodedFocusNode, figure);
        console.debug(
          "[Treemap Focus] Synthetic click by id result",
          ok,
          "for id",
          decodedFocusNode
        );
        if (ok) return;
      }

      if (attempts < 5) setTimeout(pollForSlice, 150);
    };

    console.debug("[Treemap Focus] Starting poll after initial delay", 50);
    setTimeout(pollForSlice, 50);

    const msg = `Search triggered for '${decodedFocusNode}' at ${new Date().toISOString()}`;
    console.debug("[Treemap Focus] Returning status", msg);
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
    if (!figure?.data?.length || !selectedNodeId)
      return window.dash_clientside.no_update;
    const ids = figure.data[0].ids;
    if (!Array.isArray(ids) || !ids.includes(selectedNodeId))
      return window.dash_clientside.no_update;

    function tryRestyle(attempts) {
      const plotDiv = document.querySelector("#treemap-graph .js-plotly-plot");
      if (!plotDiv || typeof window.Plotly?.restyle !== "function") {
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
    const MARGIN = 8;
    const MIN_FONT_SIZE = 9;

    // Return the BBox of an SVG element in its own local coordinate space.
    // Falls back to getBoundingClientRect when getBBox is unavailable (non-SVG host).
    function safeGetBBox(el) {
      try {
        if (typeof el.getBBox === "function") {
          var b = el.getBBox();
          if (b && (b.width > 0 || b.height > 0)) return b;
        }
      } catch (e) {}
      // Fallback: convert viewport rect to a plain object with the same shape.
      var r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, width: r.width, height: r.height };
    }

    // IE/old-Android polyfill for Element.closest().
    function closestPathbar(el) {
      var node = el;
      while (node && node !== document) {
        if (
          node.className &&
          typeof node.className === "string" &&
          node.className.indexOf("pathbar") !== -1
        )
          return node;
        if (node.classList && node.classList.contains("pathbar")) return node;
        node = node.parentNode;
      }
      return null;
    }

    function applyInsets(plotDiv) {
      var slices = plotDiv.querySelectorAll("g.slice");
      for (var si = 0; si < slices.length; si++) {
        var slice = slices[si];
        if (closestPathbar(slice)) continue;
        var surface = slice.querySelector("path.surface");
        if (!surface) continue;
        var gText = slice.querySelector("g.slicetext");
        if (!gText) continue;

        var textEls = gText.querySelectorAll("text");
        if (!textEls.length) continue;

        // Reset any previous overrides to get natural measurements.
        for (var ti = 0; ti < textEls.length; ti++) {
          textEls[ti].style.fontSize = "";
        }

        // Force a synchronous layout flush so getBBox() reads post-reset dimensions,
        // not the previously-compressed values.
        void plotDiv.getBoundingClientRect();

        // Measure surface in local SVG coordinate space — more reliable than
        // getBoundingClientRect() for SVG elements across browsers.
        var sr;
        try {
          sr = safeGetBBox(surface);
        } catch (e) {
          continue;
        }
        if (!sr || sr.width <= 0 || sr.height <= 0) continue;

        // Union bounding box of all <text> children in the same coordinate space.
        var tMinX = Infinity,
          tMaxX = -Infinity,
          tMinY = Infinity,
          tMaxY = -Infinity;
        for (var ti2 = 0; ti2 < textEls.length; ti2++) {
          var tb;
          try {
            tb = safeGetBBox(textEls[ti2]);
          } catch (e) {
            continue;
          }
          if (!tb || tb.width <= 0) continue;
          if (tb.x < tMinX) tMinX = tb.x;
          if (tb.x + tb.width > tMaxX) tMaxX = tb.x + tb.width;
          if (tb.y < tMinY) tMinY = tb.y;
          if (tb.y + tb.height > tMaxY) tMaxY = tb.y + tb.height;
        }
        if (tMinX === Infinity || tMaxX <= tMinX || tMaxY <= tMinY) continue;

        var tW = tMaxX - tMinX;
        var tH = tMaxY - tMinY;
        var srRight = sr.x + sr.width;
        var srBottom = sr.y + sr.height;

        // No overflow — nothing to do.
        if (
          tMinX >= sr.x - THRESHOLD &&
          tMaxX <= srRight + THRESHOLD &&
          tMaxY <= srBottom + THRESHOLD
        )
          continue;

        // Compute scale ratio needed to fit within the tile (with margin).
        var ratio = 1;
        var availW = sr.width - 2 * MARGIN;
        var availH = sr.height - 2 * MARGIN;
        if (tW > availW && availW > 0) ratio = Math.min(ratio, availW / tW);
        if (tH > availH && availH > 0) ratio = Math.min(ratio, availH / tH);

        if (ratio >= 1 || ratio <= 0) continue;

        for (var ti3 = 0; ti3 < textEls.length; ti3++) {
          var el = textEls[ti3];
          var sz = 0;
          try {
            sz = parseFloat(window.getComputedStyle(el).fontSize) || 0;
          } catch (e) {}
          if (sz > 0) {
            el.style.fontSize = Math.max(MIN_FONT_SIZE, sz * ratio) + "px";
          }
        }
      }
    }

    let tries = 0;

    function tryApply() {
      tries++;
      const plotDiv = document.querySelector("#treemap-graph .js-plotly-plot");
      if (!plotDiv) {
        if (tries < 30) setTimeout(tryApply, 100);
        return;
      }

      let rendered = false;
      const firstSurface = plotDiv.querySelector("g.slice path.surface");
      if (firstSurface) {
        try {
          if (firstSurface.getBBox().width > 0) rendered = true;
        } catch (e) {}
      }
      if (!rendered) {
        if (tries < 30) setTimeout(tryApply, 100);
        return;
      }

      // Reconnect observer only when Plotly has replaced the .treemaplayer element.
      const treemapLayer = plotDiv.querySelector(".treemaplayer");
      if (treemapLayer && plotDiv._observedTreemapLayer !== treemapLayer) {
        if (plotDiv._textInsetObserver) plotDiv._textInsetObserver.disconnect();
        const tileObserver = new MutationObserver(() => {
          clearTimeout(plotDiv._textInsetTimer);
          plotDiv._textInsetTimer = setTimeout(() => applyInsets(plotDiv), 50);
        });
        tileObserver.observe(treemapLayer, {
          subtree: true,
          attributes: true,
          attributeFilter: ["d"],
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
