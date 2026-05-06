window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

Object.assign(window.dash_clientside.clientside, {
  /**
   * Build a shareable URL from current filters and selected id and copy it.
   * Params included: budget_id, viewby (treemap only), spending_type, unit, period (timeseries only), focus
   *
   * @param {number} n_clicks - Button clicks (ignored aside from triggering)
   * @param {string} pathname - Current page path, e.g., '/'
   * @param {number|null} budgetId
   * @param {string} viewby
   * @param {string} spendingType
   * @param {string} unit
   * @param {string|null} period
   * @param {string|null} language
   * @param {string|null} selectedId
   * @returns {string} Status message in dummy output title.
   */
  copyShareLink: function (n_clicks, pathname, budgetId, viewby, spendingType, unit, period, language, selectedId, nodeMap) {
    try {
      if (!n_clicks) return 'Share not triggered';
      const isTimeseries = pathname?.endsWith('/timeseries');
      const params = new URLSearchParams();
      if (budgetId != null) params.set('budget_id', String(budgetId));
      if (viewby && !isTimeseries) params.set('viewby', viewby);
      if (spendingType) params.set('spending_type', spendingType);
      if (unit) params.set('unit', unit);
      if (period && isTimeseries) params.set('period', period);
      if (language) params.set('language', language);
      if (selectedId) {
        // Compact nodeMap is {short_id: {leaf: dim_id, ctx: [...]}} — direct lookup by short_id.
        let focusParam = selectedId;
        if (nodeMap) {
          const entry = nodeMap[String(selectedId)];
          if (entry) focusParam = entry.leaf ?? entry;
        }
        params.set('focus', focusParam);
      }

      const url = `${window.location.origin}${pathname || '/'}?${params.toString()}`;

      const copyViaTextarea = () => {
        const el = document.createElement('textarea');
        el.value = url;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
      };

      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(url).catch(copyViaTextarea);
      } else {
        copyViaTextarea();
      }
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
      if (!n_clicks) return window.dash_clientside.no_update;

      let graphId, filenamePrefix;
      if (!pathname || pathname === '/' || pathname.endsWith('/')) {
        graphId = 'treemap-graph';
        filenamePrefix = 'treemap';
      } else if (pathname.endsWith('/timeseries')) {
        graphId = 'timeseries-graph';
        filenamePrefix = 'timeseries';
      } else {
        return window.dash_clientside.no_update;
      }

      const container = document.getElementById(graphId);
      if (!container) {
        console.warn('[Download] Graph container not found:', graphId);
        return window.dash_clientside.no_update;
      }

      const graphDiv = container.querySelector('.js-plotly-plot') || container;
      if (!graphDiv.data || !graphDiv.layout) {
        console.warn('[Download] No Plotly data found on element');
        return window.dash_clientside.no_update;
      }

      const budgetName = budgetOptions?.find((o) => o.value === budgetId)?.label || 'unknown';
      const now = new Date();
      const timestamp = now.toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      const sanitizedBudget = budgetName.replace(/\s+/g, '_').replace(/\//g, '-');
      const unitLabel = (unit || 'ABSOLUTE').toLowerCase();
      const militarySuffix = spendingType === 'MILITARY' ? '_military' : '';
      const filename = `${filenamePrefix}_${timestamp}_${sanitizedBudget}_${unitLabel}${militarySuffix}`;

      const width = graphDiv.offsetWidth || 800;
      const height = graphDiv.offsetHeight || 600;
      const scale = 2;
      // Footer strip added below the plot so the watermark never overlaps chart content.
      const footerPx = 24;

      const svgElement = graphDiv.querySelector('svg.main-svg');
      if (!svgElement) {
        console.warn('[Download] SVG element not found, falling back to Plotly.downloadImage');
        window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
        return now.toISOString();
      }

      // Use rendered dimensions as the coordinate space; only width/height are scaled up.
      // Setting viewBox to the scaled values would shrink content to the top-left quarter.
      const svgRect = svgElement.getBoundingClientRect();
      const origW = Math.round(svgRect.width);
      const origH = Math.round(svgRect.height);
      const svgWidth = origW * scale;
      const svgHeight = origH * scale;

      // Record computed visibility/opacity for infolayer children (title, legend, etc.)
      // before cloning so CSS-driven state is baked into the serialised SVG as inline styles.
      const infoEl = svgElement.querySelector('g.infolayer');
      const infoStyles = new Map();
      if (infoEl) {
        infoEl.querySelectorAll('*').forEach((el, i) => {
          const cs = window.getComputedStyle(el);
          infoStyles.set(i, { visibility: cs.visibility, opacity: cs.opacity, display: cs.display });
        });
      }

      const svgClone = svgElement.cloneNode(true);

      // Apply baked-in visibility to infolayer clone so legend / title render.
      const infoClone = svgClone.querySelector('g.infolayer');
      if (infoClone) {
        const cloneEls = infoClone.querySelectorAll('*');
        infoStyles.forEach((s, i) => {
          const el = cloneEls[i];
          if (!el) return;
          el.style.visibility = s.visibility;
          el.style.opacity = s.opacity;
          el.style.display = s.display;
        });
      }

      svgClone.setAttribute('width', svgWidth);
      svgClone.setAttribute('height', svgHeight);
      svgClone.setAttribute('viewBox', `0 0 ${origW} ${origH}`);
      svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

      // Embed Google Font so chart text renders with Source Sans 3.
      const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
      styleEl.textContent =
        '@import url("https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap");' +
        'text, tspan { font-family: "Source Sans 3", sans-serif !important; }';
      svgClone.insertBefore(styleEl, svgClone.firstChild);

      svgClone.querySelectorAll('text, tspan').forEach((el) => {
        el.setAttribute('font-family', '"Source Sans 3", sans-serif');
      });

      const svgString = new XMLSerializer().serializeToString(svgClone);

      // Pull title / y-axis label text and layout metrics from Plotly's internal state.
      // These elements are often missing from the raw SVG clone because Plotly applies
      // CSS-based visibility that is lost on serialisation.  Drawing them on canvas
      // after the SVG image is composited is the most reliable alternative.
      const fl = graphDiv._fullLayout || {};
      const titleEl = document.getElementById('timeseries-title');
      const rawTitle = (titleEl?.textContent?.trim()) || fl.title?.text || (typeof graphDiv.layout?.title === 'string' ? graphDiv.layout.title : graphDiv.layout?.title?.text) || '';
      const rawYTitle = fl.yaxis?.title?.text ?? (typeof graphDiv.layout?.yaxis?.title === 'string' ? graphDiv.layout.yaxis.title : graphDiv.layout?.yaxis?.title?.text) ?? '';
      const sz = fl._size || {};
      const ml = (sz.l || 60) * scale;
      const mt = (sz.t || 50) * scale;
      const pw = (sz.w || width - 90) * scale;
      const ph = (sz.h || height - 75) * scale;

      // Read actual rendered font sizes from live SVG elements so text scales
      // correctly at any zoom level or screen size.
      const readPx = (selector, fallback) => {
        const el = svgElement.querySelector(selector);
        if (!el) return fallback;
        const fs = parseFloat(window.getComputedStyle(el).fontSize);
        return isNaN(fs) ? fallback : fs;
      };
      const titleFontPx = readPx('.g-gtitle text', fl.title?.font?.size || fl.font?.size || 14);
      const axisFontPx = readPx('.ytitle', fl.yaxis?.title?.font?.size || fl.font?.size || 12);
      const legendFontPx = readPx('.legend text', fl.font?.size || 12);

      // Header strip above the SVG holds the chart title with breathing room.
      const headerPx = rawTitle ? 48 : 0;
      const totalHeight = headerPx * scale + svgHeight + footerPx * scale;

      const fontLoadPromise = document.fonts?.load
        ? Promise.all([
            document.fonts.load('400 12px "Source Sans 3"'),
            document.fonts.load('600 12px "Source Sans 3"'),
          ])
        : new Promise((resolve) => setTimeout(resolve, 500));

      fontLoadPromise.then(() => {
        const canvas = document.createElement('canvas');
        canvas.width = svgWidth;   // origW * scale
        canvas.height = totalHeight;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const img = new Image();
        img.onload = () => {
          // SVG is offset downward by the header strip.
          const hOff = headerPx * scale;
          ctx.drawImage(img, 0, hOff, svgWidth, svgHeight);

          // Draw title, y-axis label, and legend via canvas so they are always present
          // regardless of SVG infolayer CSS visibility issues.
          const titleSize = titleFontPx * scale;
          const axisSize = axisFontPx * scale;
          const legendSize = legendFontPx * scale;
          const textColor = fl.font?.color || '#444444';

          if (rawTitle) {
            ctx.font = `${titleSize}px "Source Sans 3", sans-serif`;
            ctx.fillStyle = fl.title?.font?.color || textColor;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            // Truncate to fit within the plot width with side padding.
            const sidePad = 80 * scale;
            const maxW = svgWidth - sidePad * 2;
            let titleText = rawTitle;
            if (ctx.measureText(titleText).width > maxW) {
              while (titleText.length > 0 && ctx.measureText(titleText + '…').width > maxW) {
                titleText = titleText.slice(0, -1);
              }
              titleText += '…';
            }
            ctx.fillText(titleText, svgWidth / 2, hOff / 2);
          }

          if (rawYTitle) {
            ctx.save();
            ctx.font = `${axisSize}px "Source Sans 3", sans-serif`;
            ctx.fillStyle = fl.yaxis?.title?.font?.color || textColor;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.translate(ml / 2, hOff + mt + ph / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.fillText(rawYTitle, 0, 0);
            ctx.restore();
          }

          // Legend — drawn from trace data, positioned to match the Plotly layout.
          const legendTraces = (graphDiv.data || []).filter(
            (t) => t.showlegend !== false && t.name && t.visible !== false,
          );
          if (legendTraces.length > 0 && fl.showlegend !== false) {
            const swatchW = 12 * scale;
            const swatchH = 12 * scale;
            const swatchGap = 5 * scale;   // gap between swatch and label
            const itemGap = 20 * scale;    // gap between legend items

            ctx.font = `${legendSize}px "Source Sans 3", sans-serif`;

            const items = legendTraces.map((t) => ({
              label: t.name,
              color: t.marker?.color || t.line?.color || '#888888',
              labelW: ctx.measureText(t.name).width,
            }));
            const totalLegendW =
              items.reduce((sum, it) => sum + swatchW + swatchGap + it.labelW, 0) +
              (items.length - 1) * itemGap;

            // Prefer Plotly's computed pixel offset; fall back to layout calculation.
            const legOffX = fl.legend?._offsetX != null ? fl.legend._offsetX * scale : null;
            const legOffY = fl.legend?._offsetY != null ? fl.legend._offsetY * scale : null;

            const legendCX = legOffX != null ? legOffX + (fl.legend?._width || 0) * scale / 2 : ml + pw / 2;
            const legendTopY =
              legOffY != null
                ? hOff + legOffY
                : hOff + mt + ph + Math.abs((fl.legend?.y ?? -0.2)) * ph - swatchH;

            let curX = legendCX - totalLegendW / 2;
            const swatchY = legendTopY;

            items.forEach((item) => {
              ctx.fillStyle = item.color;
              ctx.fillRect(curX, swatchY, swatchW, swatchH);
              ctx.fillStyle = textColor;
              ctx.textAlign = 'left';
              ctx.textBaseline = 'middle';
              ctx.fillText(item.label, curX + swatchW + swatchGap, swatchY + swatchH / 2);
              curX += swatchW + swatchGap + item.labelW + itemGap;
            });
          }

          // Watermark
          ctx.font = `${12 * scale}px "Source Sans 3", sans-serif`;
          ctx.fillStyle = '#333333';
          ctx.textAlign = 'right';
          ctx.textBaseline = 'alphabetic';
          ctx.fillText(
            `Stiftung Wissenschaft und Politik (SWP), ${now.getFullYear()} | CC BY 4.0`,
            canvas.width - 10 * scale,
            canvas.height - 8 * scale,
          );

          canvas.toBlob((pngBlob) => {
            const downloadUrl = URL.createObjectURL(pngBlob);
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = `${filename}.png`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(downloadUrl);
            console.debug('[Download] PNG downloaded:', filename);
          }, 'image/png');
        };
        img.onerror = (err) => {
          console.error('[Download] SVG to image failed:', err);
          window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
        };
        img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgString)));
      }).catch((err) => {
        console.error('[Download] Export failed:', err);
        window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
      });

      return now.toISOString();
    } catch (e) {
      console.error('[Download] Error:', e);
      return window.dash_clientside.no_update;
    }
  },
});
