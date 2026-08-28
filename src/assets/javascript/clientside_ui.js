window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.clientside = window.dash_clientside.clientside || {};

function hasDashComponent(id) {
  try {
    return Boolean(window.dash_component_api?.getLayout?.(id));
  } catch (_) {
    return false;
  }
}

Object.assign(window.dash_clientside.clientside, {
  hideTreemapSpinner: function (figure, style) {
    if (!style || style.visibility !== 'visible') {
      return window.dash_clientside.no_update;
    }
    var el = document.getElementById('treemap-spinner');
    if (el) el.style.display = 'none';
    return window.dash_clientside.no_update;
  },

  showTreemapSpinner: function () {
    var spinner = document.getElementById('treemap-spinner');
    if (spinner) spinner.style.display = '';
    if (hasDashComponent('treemap-page-ready')) {
      window.dash_clientside.set_props('treemap-page-ready', { n_intervals: Date.now() });
    }
    return window.dash_clientside.no_update;
  },

  showTimeseriesSpinner: function () {
    var spinner = document.getElementById('timeseries-spinner');
    if (spinner) spinner.style.display = '';
    if (hasDashComponent('timeseries-page-ready')) {
      window.dash_clientside.set_props('timeseries-page-ready', { n_intervals: Date.now() });
    }
    return window.dash_clientside.no_update;
  },

  hideTimeseriesSpinner: function (figure, style) {
    if (!style || style.visibility !== 'visible') {
      return window.dash_clientside.no_update;
    }
    var el = document.getElementById('timeseries-spinner');
    if (el) el.style.display = 'none';
    return window.dash_clientside.no_update;
  },

  hideTreemapSpinnerOnToast: function (isOpen) {
    if (isOpen) {
      var el = document.getElementById('treemap-spinner');
      if (el) el.style.display = 'none';
    }
    return window.dash_clientside.no_update;
  },

  // ---------------------------------------------------------------------------
  // adjustTimeseriesTicks
  //
  // Adjusts quarterly x-axis tick labels based on viewport width.
  //
  // On narrow screens (< 640 px) only Q1 ticks show the year; all others are
  // hidden. On wider screens every tick shows the full "YYYY-Qn" label.
  // Only runs when tickInfo is non-null (REPORT budget, all periods selected).
  //
  // @param {number} windowWidth - Current viewport width in pixels.
  // @param {object|null} tickInfo - {tickvals: string[]} ISO date strings, or null.
  // @param {object} figure - Current Plotly figure object.
  // @returns Updated figure or no_update.
  // ---------------------------------------------------------------------------
  adjustTimeseriesTicks: function (windowWidth, tickInfo, figure) {
    if (!tickInfo || !tickInfo.tickvals || !tickInfo.tickvals.length || !figure) {
      return window.dash_clientside.no_update;
    }

    const THRESHOLD = 640;
    const isNarrow = windowWidth < THRESHOLD;

    // Avoid redundant figure re-renders when neither the data nor the narrow
    // state has changed since the last time this callback ran.
    const cacheKey = isNarrow + '|' + tickInfo.tickvals.join(',');
    if (window._tsTick_lastKey === cacheKey) {
      return window.dash_clientside.no_update;
    }
    window._tsTick_lastKey = cacheKey;

    const tickvals = tickInfo.tickvals;

    // Derive quarter from the ISO date string (e.g. "2022-03-31T00:00:00").
    // Months: 03→Q1, 06→Q2, 09→Q3, 12→Q4.
    function quarterLabel(isoStr) {
      const month = parseInt(isoStr.substring(5, 7), 10);
      return month / 3; // 1, 2, 3, or 4
    }

    const ticktext = tickvals.map(function (ts) {
      const year = ts.substring(0, 4);
      const q = quarterLabel(ts);
      if (isNarrow) {
        return q === 1 ? year : '';
      }
      return year + '-Q' + q;
    });

    const updatedFigure = JSON.parse(JSON.stringify(figure));
    updatedFigure.layout = updatedFigure.layout || {};
    updatedFigure.layout.xaxis = Object.assign({}, updatedFigure.layout.xaxis, {
      tickmode: 'array',
      tickvals: tickvals,
      ticktext: ticktext,
      tickangle: -45,
    });

    // When ticktext contains empty strings (narrow screen, non-Q1 ticks), Plotly's
    // %{x} in the hovertemplate shows the empty ticktext instead of the formatted date.
    // Fix: store the full "YYYY-Qn" label in customdata[1] and use that in the template.
    if (updatedFigure.data) {
      updatedFigure.data.forEach(function (trace) {
        if (!trace.x) return;
        trace.customdata = trace.x.map(function (xVal, i) {
          const unitLabel = trace.customdata && trace.customdata[i] && trace.customdata[i][0];
          const d = new Date(xVal);
          const q = Math.ceil((d.getMonth() + 1) / 3);
          const qLabel = d.getFullYear() + '-Q' + q;
          return [unitLabel, qLabel];
        });
        if (trace.hovertemplate && trace.hovertemplate.indexOf('%{x}') !== -1) {
          trace.hovertemplate = trace.hovertemplate.replace('%{x}', '%{customdata[1]}');
        }
      });
    }

    return updatedFigure;
  },
});

// Dash can mount a page-local graph and apply its first figure before the
// downstream clientside callback is registered. Bind directly to Plotly as a
// page-mount-safe completion signal; the regular callbacks above remain the
// fast path for later filter updates.
function bindSpinnerAfterPlot(graphId, spinnerId) {
  var graph = document.getElementById(graphId);
  var plot = graph && graph.querySelector('.js-plotly-plot');
  if (!plot || typeof plot.on !== 'function') return;
  if (plot.__budgetTrackerSpinnerAfterPlot) return;

  var hideWhenVisible = function () {
    var currentGraph = document.getElementById(graphId);
    if (!currentGraph) return;
    var graphStyle = window.getComputedStyle(currentGraph);
    if (graphStyle.display === 'none' || graphStyle.visibility !== 'visible') return;
    var spinner = document.getElementById(spinnerId);
    if (spinner) spinner.style.display = 'none';
  };

  plot.__budgetTrackerSpinnerAfterPlot = hideWhenVisible;
  plot.on('plotly_afterplot', hideWhenVisible);

  // Covers a plot that Dash/React reused before this mount observer bound.
  if (plot._fullLayout) hideWhenVisible();
}

(function installSpinnerAfterPlotObserver() {
  function bind() {
    bindSpinnerAfterPlot('treemap-graph', 'treemap-spinner');
    bindSpinnerAfterPlot('timeseries-graph', 'timeseries-spinner');
  }

  function start() {
    new MutationObserver(bind).observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    bind();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
