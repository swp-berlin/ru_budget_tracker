window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

Object.assign(window.dash_clientside.clientside, {
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
  copyShareLink: function (n_clicks, pathname, budgetId, viewby, spendingType, unit, selectedId, nodeMap) {
    try {
      if (!n_clicks) return 'Share not triggered';
      const params = new URLSearchParams();
      if (budgetId != null) params.set('budget_id', String(budgetId));
      if (viewby) params.set('viewby', viewby);
      if (spendingType) params.set('spending_type', spendingType);
      if (unit) params.set('unit', unit);
      if (selectedId) {
        // Use the short dimension_id from the node map instead of the full path.
        const nodeInfo = nodeMap && nodeMap[selectedId];
        const focusParam = nodeInfo ? String(nodeInfo.dimension_id) : selectedId;
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
      if (!pathname || pathname === '/') {
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

      const svgElement = graphDiv.querySelector('svg.main-svg');
      if (!svgElement) {
        console.warn('[Download] SVG element not found, falling back to Plotly.downloadImage');
        window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
        return now.toISOString();
      }

      const svgClone = svgElement.cloneNode(true);
      const svgWidth = parseInt(svgElement.getAttribute('width')) || width;
      const svgHeight = parseInt(svgElement.getAttribute('height')) || height;

      // Embed Google Font for correct text rendering in exported image
      const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
      styleEl.textContent = '@import url("https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap"); text, tspan { font-family: "Source Sans 3", sans-serif !important; }';
      svgClone.insertBefore(styleEl, svgClone.firstChild);

      svgClone.querySelectorAll('text, tspan').forEach((el) => {
        el.setAttribute('font-family', '"Source Sans 3", sans-serif');
      });

      const watermark = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      watermark.setAttribute('x', svgWidth - 10);
      watermark.setAttribute('y', svgHeight - 8);
      watermark.setAttribute('text-anchor', 'end');
      watermark.setAttribute('font-family', '"Source Sans 3", sans-serif');
      watermark.setAttribute('font-size', '12');
      watermark.setAttribute('fill', '#333333');
      watermark.textContent = `Stiftung Wissenschaft und Politik (SWP), ${now.getFullYear()} | CC BY 4.0`;
      svgClone.appendChild(watermark);

      svgClone.setAttribute('width', svgWidth);
      svgClone.setAttribute('height', svgHeight);
      svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

      const svgString = new XMLSerializer().serializeToString(svgClone);

      // Create a hidden element to trigger font loading
      const fontLoader = document.createElement('div');
      fontLoader.style.cssText = 'position:absolute;left:-9999px;font-family:"Source Sans 3",sans-serif;';
      fontLoader.textContent = 'Font loader';
      document.body.appendChild(fontLoader);

      const fontLoadPromise = document.fonts?.load
        ? Promise.all([
            document.fonts.load('400 12px "Source Sans 3"'),
            document.fonts.load('600 12px "Source Sans 3"'),
          ])
        : new Promise((resolve) => setTimeout(resolve, 500));

      fontLoadPromise.then(() => {
        const canvas = document.createElement('canvas');
        canvas.width = svgWidth * scale;
        canvas.height = svgHeight * scale;
        const ctx = canvas.getContext('2d');
        ctx.scale(scale, scale);
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, svgWidth, svgHeight);

        const img = new Image();
        img.onload = () => {
          ctx.drawImage(img, 0, 0);
          document.body.removeChild(fontLoader);
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
          document.body.removeChild(fontLoader);
          window.Plotly.downloadImage(graphDiv, { format: 'png', width: width * scale, height: height * scale, filename });
        };
        img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgString)));
      }).catch((err) => {
        console.error('[Download] Font loading failed:', err);
        document.body.removeChild(fontLoader);
      });

      return now.toISOString();
    } catch (e) {
      console.error('[Download] Error:', e);
      return window.dash_clientside.no_update;
    }
  },
});
