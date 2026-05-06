window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

Object.assign(window.dash_clientside.clientside, {

  // ---------------------------------------------------------------------------
  // copyShareLink
  //
  // Builds a shareable URL from the current filter state (budget, view mode,
  // spending type, unit, and optionally a focused node) and copies it to the
  // clipboard.  Returns a status string that Dash writes into a dummy element.
  // ---------------------------------------------------------------------------
  copyShareLink: function (n_clicks, pathname, budgetId, viewby, spendingType, unit, selectedId, nodeMap) {
    try {
      if (!n_clicks) return 'Share not triggered';

      const params = new URLSearchParams();
      if (budgetId != null) params.set('budget_id', String(budgetId));
      if (viewby) params.set('viewby', viewby);
      if (spendingType) params.set('spending_type', spendingType);
      if (unit) params.set('unit', unit);

      if (selectedId) {
        // nodeMap is keyed by dim_id: { ru: path, en: path }.
        // We resolve the selected path back to a stable dim_id so the link
        // works regardless of the current language setting.
        let focusParam = selectedId;
        if (nodeMap) {
          for (const [dimId, paths] of Object.entries(nodeMap)) {
            if (paths.ru === selectedId || paths.en === selectedId) {
              focusParam = dimId;
              break;
            }
          }
        }
        params.set('focus', focusParam);
      }

      const url = `${window.location.origin}${pathname || '/'}?${params.toString()}`;

      // navigator.clipboard requires HTTPS; fall back to execCommand for HTTP.
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

  // ---------------------------------------------------------------------------
  // downloadPlotImage
  //
  // Exports the currently visible Plotly chart (treemap or timeseries) as a
  // high-resolution PNG and triggers a browser download.
  //
  // How it works at a high level:
  //   1. Fetch the Source Sans 3 font file from the server and encode it as
  //      base64 so it can be embedded directly inside the SVG.  This is
  //      necessary because when an SVG is converted to an image the browser
  //      runs it in an isolated context where external font URLs are blocked.
  //   2. Clone Plotly's SVG, inject the embedded font as a <style> block, and
  //      serialize the SVG to a data URI.
  //   3. Draw that SVG image onto an HTML Canvas at 2× resolution.
  //   4. Draw any text that Plotly hides via CSS (title, axis label) directly
  //      on the canvas using the canvas text API, which can use page fonts.
  //   5. Add a watermark, then export the canvas as a PNG file.
  // ---------------------------------------------------------------------------
  downloadPlotImage: function (n_clicks, pathname, budgetId, budgetOptions, unit, spendingType, period) {
    try {
      if (!n_clicks) return window.dash_clientside.no_update;

      // ------------------------------------------------------------------
      // Step 1 — Identify which chart to export based on the current page.
      // ------------------------------------------------------------------
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

      // .js-plotly-plot is the element Plotly attaches its internal state to.
      const graphDiv = container.querySelector('.js-plotly-plot') || container;
      if (!graphDiv.data || !graphDiv.layout) {
        console.warn('[Download] No Plotly data found on element');
        return window.dash_clientside.no_update;
      }

      // ------------------------------------------------------------------
      // Step 2 — Build the output filename from current filter values.
      // ------------------------------------------------------------------
      const budgetName = budgetOptions?.find((o) => o.value === budgetId)?.label || 'unknown';
      const now = new Date();
      const timestamp = now.toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      const sanitizedBudget = budgetName.replace(/\s+/g, '_').replace(/\//g, '-');
      const unitLabel = (unit || 'ABSOLUTE').toLowerCase();
      const militarySuffix = spendingType === 'MILITARY' ? '_military' : '';
      const periodSuffix = (filenamePrefix === 'timeseries' && period && period !== 'ALL') ? `_${period.toLowerCase()}` : '';
      const filename = `${filenamePrefix}_${timestamp}_${sanitizedBudget}_${unitLabel}${militarySuffix}${periodSuffix}`;

      // ------------------------------------------------------------------
      // Step 3 — Measure the chart and set up canvas dimensions.
      // ------------------------------------------------------------------
      const width = graphDiv.offsetWidth || 800;
      const height = graphDiv.offsetHeight || 600;
      const scale = 2;           // render at 2× for sharper output
      const footerPx = 24;       // height of the watermark strip below the chart

      const svgElement = graphDiv.querySelector('svg.main-svg');
      if (!svgElement) {
        // Fallback: let Plotly handle the export if we can't find the SVG.
        console.warn('[Download] SVG element not found, falling back to Plotly.downloadImage');
        window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
        return now.toISOString();
      }

      // Use the rendered pixel dimensions as the SVG coordinate space.
      // Scaling the viewBox instead of width/height would shrink content.
      const svgRect = svgElement.getBoundingClientRect();
      const origW = Math.round(svgRect.width);
      const origH = Math.round(svgRect.height);
      const svgWidth = origW * scale;
      const svgHeight = origH * scale;

      // ------------------------------------------------------------------
      // Step 4 — Snapshot visibility of the infolayer (title, legend, etc.)
      //           before cloning.
      //
      //           Plotly controls visibility of these elements via CSS classes
      //           that are lost when the SVG is cloned and serialized.  We
      //           read the computed visibility now and bake it into inline
      //           styles on the clone so the elements always render.
      // ------------------------------------------------------------------
      const infoEl = svgElement.querySelector('g.infolayer');
      const infoStyles = new Map();
      if (infoEl) {
        infoEl.querySelectorAll('*').forEach((el, i) => {
          const cs = window.getComputedStyle(el);
          infoStyles.set(i, { visibility: cs.visibility, opacity: cs.opacity, display: cs.display });
        });
      }

      const svgClone = svgElement.cloneNode(true);

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

      // ------------------------------------------------------------------
      // Step 5 — Read layout metrics and font sizes from the live chart so
      //           the canvas text overlays (title, axis label, legend) match
      //           the rendered chart.
      // ------------------------------------------------------------------
      const fl = graphDiv._fullLayout || {};
      const titleEl = document.getElementById('timeseries-title');
      const rawTitle = (titleEl?.textContent?.trim())
        || fl.title?.text?.trim()
        || (typeof graphDiv.layout?.title === 'string' ? graphDiv.layout.title.trim() : graphDiv.layout?.title?.text?.trim())
        || '';
      const rawYTitle = fl.yaxis?.title?.text
        ?? (typeof graphDiv.layout?.yaxis?.title === 'string' ? graphDiv.layout.yaxis.title : graphDiv.layout?.yaxis?.title?.text)
        ?? '';
      const sz = fl._size || {};
      const ml = (sz.l || 60) * scale;
      const mt = (sz.t || 50) * scale;
      const pw = (sz.w || width - 90) * scale;
      const ph = (sz.h || height - 75) * scale;

      // Read font sizes from the live SVG so the export matches the screen.
      const readPx = (selector, fallback) => {
        const el = svgElement.querySelector(selector);
        if (!el) return fallback;
        const fs = parseFloat(window.getComputedStyle(el).fontSize);
        return isNaN(fs) ? fallback : fs;
      };
      const titleFontPx = readPx('.g-gtitle text', fl.title?.font?.size || fl.font?.size || 14);
      const axisFontPx = readPx('.ytitle', fl.yaxis?.title?.font?.size || fl.font?.size || 12);
      const legendFontPx = readPx('.legend text', fl.font?.size || 12);

      // If the chart has a title, add a header strip above the SVG for it.
      const headerPx = rawTitle ? 48 : 0;
      const totalHeight = headerPx * scale + svgHeight + footerPx * scale;

      // ------------------------------------------------------------------
      // Step 6 — Fetch the font file and embed it in the SVG.
      //
      //           When an SVG is loaded as an <img> (which is how we convert
      //           it to a canvas bitmap), the browser refuses to load external
      //           resources — including font files.  The only way to supply a
      //           custom font is to embed it as a base64 data URI directly
      //           inside a <style> block in the SVG itself.
      //
      //           We use a relative URL so this works regardless of what path
      //           the Dash app is mounted on (e.g. /ru-budget-tracker/).
      // ------------------------------------------------------------------
      const fontLoadPromise = fetch('assets/fonts/Source_Sans_3/SourceSans3-VariableFont_wght.ttf')
        .then((r) => r.arrayBuffer())
        .then((buf) => {
          // Convert the binary font data to a base64 string.
          // We process it in chunks of 8 192 bytes because String.fromCharCode
          // crashes with a stack overflow when called with more than ~65 000
          // arguments at once.
          const bytes = new Uint8Array(buf);
          let binary = '';
          for (let i = 0; i < bytes.length; i += 8192) {
            binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
          }
          const b64 = btoa(binary);

          // Return a CSS block that (a) registers the font via @font-face and
          // (b) forces every element in the SVG to use it.
          return (
            `@font-face { font-family: "Source Sans 3"; src: url("data:font/truetype;base64,${b64}") format("truetype"); font-weight: 100 900; }` +
            '* { font-family: "Source Sans 3", sans-serif !important; }'
          );
        })
        .then((fontCss) => {
          // Inject the font CSS as the first child of the SVG so it applies
          // to all elements before Plotly's own styles.
          const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
          styleEl.textContent = fontCss;
          svgClone.insertBefore(styleEl, svgClone.firstChild);

          // Also ensure the font is fully loaded in the page context so the
          // canvas text overlays (title, watermark, etc.) render correctly.
          return document.fonts?.load
            ? Promise.all([
                document.fonts.load('400 12px "Source Sans 3"'),
                document.fonts.load('600 12px "Source Sans 3"'),
              ])
            : new Promise((resolve) => setTimeout(resolve, 500));
        });

      // ------------------------------------------------------------------
      // Step 7 — Serialize the SVG and render it onto a canvas.
      // ------------------------------------------------------------------
      fontLoadPromise.then(() => {
        const svgString = new XMLSerializer().serializeToString(svgClone);

        const canvas = document.createElement('canvas');
        canvas.width = svgWidth;
        canvas.height = totalHeight;
        const ctx = canvas.getContext('2d');

        // White background (SVG exports are transparent by default).
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Load the serialized SVG as an image and draw it onto the canvas.
        const img = new Image();
        img.onload = () => {
          // The SVG occupies the middle band; header and footer sit above/below.
          const hOff = headerPx * scale;
          ctx.drawImage(img, 0, hOff, svgWidth, svgHeight);

          // ----------------------------------------------------------------
          // Step 8 — Draw text overlays directly on the canvas.
          //
          //           Plotly hides chart titles and axis labels via CSS when
          //           the figure is in a certain state.  Because we snapshot
          //           visibility in Step 4 for the SVG content layer but not
          //           for all layout text, the safest approach is to redraw
          //           titles, axis labels, and the legend ourselves using the
          //           canvas 2D API, which has access to page-loaded fonts.
          // ----------------------------------------------------------------
          const textColor = fl.font?.color || '#444444';

          // Chart title — centred in the header strip above the SVG.
          if (rawTitle) {
            const titleSize = titleFontPx * scale;
            ctx.font = `${titleSize}px "Source Sans 3", sans-serif`;
            ctx.fillStyle = fl.title?.font?.color || textColor;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            // Truncate with an ellipsis if the title is wider than the canvas.
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

          // Y-axis label — rotated 90° and placed in the left margin.
          if (rawYTitle) {
            const axisSize = axisFontPx * scale;
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

          // Legend — drawn from the trace data, positioned to match Plotly.
          const legendTraces = (graphDiv.data || []).filter(
            (t) => t.showlegend !== false && t.name && t.visible !== false,
          );
          if (legendTraces.length > 0 && fl.showlegend !== false) {
            const legendSize = legendFontPx * scale;
            const swatchW = 12 * scale;
            const swatchH = 12 * scale;
            const swatchGap = 5 * scale;
            const itemGap = 20 * scale;

            ctx.font = `${legendSize}px "Source Sans 3", sans-serif`;

            const items = legendTraces.map((t) => ({
              label: t.name,
              color: t.marker?.color || t.line?.color || '#888888',
              labelW: ctx.measureText(t.name).width,
            }));
            const totalLegendW =
              items.reduce((sum, it) => sum + swatchW + swatchGap + it.labelW, 0) +
              (items.length - 1) * itemGap;

            const legOffX = fl.legend?._offsetX != null ? fl.legend._offsetX * scale : null;
            const legOffY = fl.legend?._offsetY != null ? fl.legend._offsetY * scale : null;
            const legendCX = legOffX != null ? legOffX + (fl.legend?._width || 0) * scale / 2 : ml + pw / 2;
            const legendTopY = legOffY != null
              ? hOff + legOffY
              : hOff + mt + ph + Math.abs((fl.legend?.y ?? -0.2)) * ph - swatchH;

            let curX = legendCX - totalLegendW / 2;
            items.forEach((item) => {
              ctx.fillStyle = item.color;
              ctx.fillRect(curX, legendTopY, swatchW, swatchH);
              ctx.fillStyle = textColor;
              ctx.textAlign = 'left';
              ctx.textBaseline = 'middle';
              ctx.fillText(item.label, curX + swatchW + swatchGap, legendTopY + swatchH / 2);
              curX += swatchW + swatchGap + item.labelW + itemGap;
            });
          }

          // Watermark in the footer strip.
          ctx.font = `${12 * scale}px "Source Sans 3", sans-serif`;
          ctx.fillStyle = '#333333';
          ctx.textAlign = 'right';
          ctx.textBaseline = 'alphabetic';
          ctx.fillText(
            `Stiftung Wissenschaft und Politik (SWP), ${now.getFullYear()} | CC BY 4.0`,
            canvas.width - 10 * scale,
            canvas.height - 8 * scale,
          );

          // ----------------------------------------------------------------
          // Step 9 — Convert the canvas to a PNG and trigger the download.
          // ----------------------------------------------------------------
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
