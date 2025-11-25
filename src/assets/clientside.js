// Ensure the top-level dash_clientside object exists
window.dash_clientside = window.dash_clientside || {};

// Define the 'clientside' namespace and all its functions
window.dash_clientside.clientside = {
  /**
   * Finds a Plotly treemap node by its label text and simulates a click on it.
   * This function is triggered by a clientside_callback in Dash.
   *
   * @param {object} focusNodeData - The data from the `focus-node-store`.
   *                                 Expected to be `{ node: "Node Label", timestamp: "..." }`.
   * @returns {string} A status message for the dummy output component.
   */
  findAndClickSlice: function (focusNodeData) {
    // Guard against empty data on app load
    if (!focusNodeData || !focusNodeData.node) {
      return `No node specified at ${new Date().toISOString()}`;
    }

    // Decode the focus node in case it's URL-encoded
    const focusNode = decodeURIComponent(focusNodeData.node).trim();

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

    // Use longer initial delay if this might be a subsequent load or retrigger
    const initialDelay = focusNodeData.retrigger ? 500 : 300;

    const pollForSlice = () => {
      attempts++;

      // Try to find and click the slice
      if (findAndClickSlice(focusNode)) {
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
    return `Search triggered for '${focusNode}' at ${new Date().toISOString()}`;
  }
};
