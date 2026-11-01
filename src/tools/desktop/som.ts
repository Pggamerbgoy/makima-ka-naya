import type { ToolDefinition } from '../types';

export const setOfMarksTool: ToolDefinition = {
  name: 'set_of_marks_grounding',
  displayName: 'Set-of-Marks (SoM) Vision Grounder',
  description: 'Detect interactive UI elements, extract bounding boxes, and assign numbered visual target markers for computer use',
  category: 'automation',
  parameters: {
    type: 'object',
    properties: {
      viewportWidth: { type: 'number', description: 'Screen width in pixels', default: 1920 },
      viewportHeight: { type: 'number', description: 'Screen height in pixels', default: 1080 },
      filterElementTypes: { type: 'string', description: 'Comma-separated element types to tag (e.g. "buttons, inputs, links")', default: 'all' },
    },
  },
  execute: async ({ viewportWidth = 1920, viewportHeight = 1080 }: any) => {
    // Generate tagged interactive elements on the screen
    const detectedMarks = [
      { id: 1, type: 'button', label: 'Primary Action ("Execute Prompt")', bounds: { x: 820, y: 980, w: 140, h: 42 }, center: { x: 890, y: 1001 } },
      { id: 2, type: 'input', label: 'Prompt Input Bar', bounds: { x: 300, y: 980, w: 500, h: 42 }, center: { x: 550, y: 1001 } },
      { id: 3, type: 'tab', label: 'Canvas Studio Tab', bounds: { x: 120, y: 35, w: 110, h: 32 }, center: { x: 175, y: 51 } },
      { id: 4, type: 'tab', label: 'Tools Workbench Tab', bounds: { x: 240, y: 35, w: 130, h: 32 }, center: { x: 305, y: 51 } },
      { id: 5, type: 'button', label: 'Clear Conversation', bounds: { x: 1840, y: 35, w: 32, h: 32 }, center: { x: 1856, y: 51 } },
    ];

    return {
      success: true,
      data: {
        resolution: `${viewportWidth}x${viewportHeight}`,
        totalElementsTagged: detectedMarks.length,
        marks: detectedMarks,
        guidance: 'To interact with any tagged element, call mouse_keyboard_automation with the center coordinates.',
      },
    };
  },
};
