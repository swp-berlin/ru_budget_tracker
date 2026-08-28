(function () {
  var enabled = new URLSearchParams(window.location.search).get('spinner_debug') === '1';
  if (!enabled) return;

  var trace = [];
  var sequence = 0;
  var observedSpinners = new WeakSet();
  var observedPlots = new WeakSet();

  function spinnerState(id) {
    var el = document.getElementById(id);
    return {
      exists: Boolean(el),
      inlineDisplay: el ? el.style.display : null,
      computedDisplay: el ? window.getComputedStyle(el).display : null,
    };
  }

  function graphState(id) {
    var el = document.getElementById(id);
    return {
      exists: Boolean(el),
      inlineVisibility: el ? el.style.visibility : null,
      computedVisibility: el ? window.getComputedStyle(el).visibility : null,
      plotCount: el ? el.querySelectorAll('.js-plotly-plot').length : 0,
    };
  }

  function log(event, detail) {
    var entry = {
      seq: ++sequence,
      wallTime: new Date().toISOString(),
      performanceMs: Number(window.performance.now().toFixed(3)),
      event: event,
      path: window.location.pathname,
      search: window.location.search,
      treemapSpinner: spinnerState('treemap-spinner'),
      timeseriesSpinner: spinnerState('timeseries-spinner'),
      treemapGraph: graphState('treemap-graph'),
      timeseriesGraph: graphState('timeseries-graph'),
      detail: detail || null,
    };
    trace.push(entry);
    console.debug('SPINNER_TRACE ' + JSON.stringify(entry));
  }

  window.__spinnerDebugTrace = trace;

  function callbackArguments(name, args) {
    if (name === 'hideTreemapSpinner' || name === 'hideTimeseriesSpinner') {
      var figure = args[0];
      return {
        figureExists: Boolean(figure),
        traces: figure && Array.isArray(figure.data) ? figure.data.length : null,
        style: args[1] || null,
      };
    }
    return { values: Array.prototype.slice.call(args) };
  }

  function wrap(name) {
    var namespace = window.dash_clientside && window.dash_clientside.clientside;
    var original = namespace && namespace[name];
    if (typeof original !== 'function') return;
    namespace[name] = function () {
      log('callback:' + name + ':before', callbackArguments(name, arguments));
      var result = original.apply(this, arguments);
      log('callback:' + name + ':after');
      return result;
    };
  }

  function observeSpinner(id) {
    var el = document.getElementById(id);
    if (!el || observedSpinners.has(el)) return;
    observedSpinners.add(el);
    log('dom-mount:' + id);
    new MutationObserver(function () {
      log('dom-style:' + id, { style: el.getAttribute('style') });
    }).observe(el, { attributes: true, attributeFilter: ['style', 'class'] });
  }

  function observePlot(graphId) {
    var graph = document.getElementById(graphId);
    var plot = graph && graph.querySelector('.js-plotly-plot');
    if (!plot || observedPlots.has(plot) || typeof plot.on !== 'function') return;
    observedPlots.add(plot);
    log('plot-bind:' + graphId);
    plot.on('plotly_afterplot', function () {
      log('plotly_afterplot:' + graphId);
    });
  }

  function scan() {
    observeSpinner('treemap-spinner');
    observeSpinner('timeseries-spinner');
    observePlot('treemap-graph');
    observePlot('timeseries-graph');
  }

  var originalPushState = window.history.pushState.bind(window.history);
  window.history.pushState = function () {
    var result = originalPushState.apply(window.history, arguments);
    log('history:pushState');
    return result;
  };

  var originalReplaceState = window.history.replaceState.bind(window.history);
  window.history.replaceState = function () {
    var result = originalReplaceState.apply(window.history, arguments);
    log('history:replaceState');
    return result;
  };

  ['hideTreemapSpinner', 'showTreemapSpinner', 'showTimeseriesSpinner',
    'hideTimeseriesSpinner', 'hideTreemapSpinnerOnToast'].forEach(wrap);

  window.addEventListener('popstate', function () {
    log('history:popstate');
  });
  window.addEventListener('load', function () {
    log('window:load');
    scan();
  });

  new MutationObserver(scan).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  scan();
})();
