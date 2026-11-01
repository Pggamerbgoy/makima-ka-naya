export interface ToolResult {
  success: boolean;
  data?: unknown;
  error?: string;
}

export interface ToolDefinition<TArgs = any> {
  name: string;
  displayName: string;
  description: string;
  category: string;
  parameters: {
    type: string;
    properties?: Record<string, unknown>;
    required?: string[];
  };
  execute: (args: TArgs) => Promise<ToolResult>;
}
