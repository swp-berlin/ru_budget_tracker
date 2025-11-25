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
    // Parse the URL search string to get the focus parameter
    if (!search) {
      return `No search parameters at ${new Date().toISOString()}`;
    }

    // Parse query parameters from URL
    const params = new URLSearchParams(search.replace('?', ''));
    const focusNode = params.get('focus');

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
    function findAndClickSlice(nodeLabel) {
      // Step 1: Find element with id="treemap-graph"
      const graphDiv = document.getElementById('treemap-graph');
      if (!graphDiv) return false;

      // Step 2: Find element with class="treemaplayer" within treemap-graph
      const treemapLayer = graphDiv.querySelector('.treemaplayer');
      if (!treemapLayer) return false;

      // Step 3: Find element with class="trace treemap" within treemaplayer
      const traceTreemap = treemapLayer.querySelector('.trace.treemap');
      if (!traceTreemap) return false;

      // Step 4: Find all g-tags with class="slice cursor-pointer" within trace treemap
      const sliceElements = traceTreemap.querySelectorAll('g.slice.cursor-pointer');
      if (sliceElements.length === 0) return false;

      // Step 5: Search through each slice for the target text
      for (let i = 0; i < sliceElements.length; i++) {
        const slice = sliceElements[i];

        // Look for g-tag with class="slicetext" within this slice
        const sliceTextGroup = slice.querySelector('g.slicetext');
        if (!sliceTextGroup) continue;

        // Look for text element within the slicetext group
        const textElement = sliceTextGroup.querySelector('text');
        if (!textElement) continue;

        // Check if this text matches our target
        const label = textElement.textContent?.trim() || '';
        if (label.toLowerCase() === nodeLabel.toLowerCase()) {
          // Find clickable element within this slice - look for path element first
          let clickableElement = slice.querySelector('path.surface') || slice.querySelector('path') || slice;

          // Use multiple event types for better compatibility
          const events = ['mousedown', 'mouseup', 'click'];

          // Dispatch click events on the clickable element
          events.forEach(eventType => {
            const event = new MouseEvent(eventType, {
              view: window,
              bubbles: true,
              cancelable: true,
              clientX: 100, // Add coordinates for more realistic event
              clientY: 100
            });
            clickableElement.dispatchEvent(event);
          });

          return true;
        }
      }

      return false;
    }

    // Start polling mechanism to find the slice (in case DOM is still loading)
    let attempts = 0;
    const maxAttempts = 5; // Maximum polling attempts
    const pollInterval = 500; // Milliseconds between attempts

    // Use longer initial delay to allow treemap to render
    const initialDelay = 300;

    const pollForSlice = () => {
      attempts++;

      // Try to find and click the slice
      if (findAndClickSlice(decodedFocusNode)) {
        return;
      }

      // Continue polling if not found and under max attempts
      if (attempts < maxAttempts) {
        setTimeout(pollForSlice, pollInterval);
      }
    };

    // Start polling after the calculated initial delay
    setTimeout(pollForSlice, initialDelay);

    // Return a status message for the dummy output component
    return `Search triggered for '${decodedFocusNode}' at ${new Date().toISOString()}`;
  }
};
