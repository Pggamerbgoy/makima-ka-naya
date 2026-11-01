import type { ToolDefinition } from '../types';

export const webFetcherTool: ToolDefinition = {
  name: 'web_fetcher',
  displayName: 'HTTP REST & Web Page Fetcher',
  description: 'Fetch real-time web pages, REST API endpoints, JSON data payloads, or online documentation with custom headers',
  category: 'web',
  parameters: {
    type: 'object',
    properties: {
      url: { type: 'string', description: 'Target URL to fetch (HTTP or HTTPS)' },
      method: { type: 'string', description: 'HTTP method', enum: ['GET', 'POST', 'HEAD'], default: 'GET' },
      extractTextOnly: { type: 'boolean', description: 'Strip HTML tags and return clean text content', default: true },
    },
    required: ['url'],
  },
  execute: async ({ url, method = 'GET', extractTextOnly = true }: any) => {
    try {
      const resp = await fetch(url, {
        method,
        headers: {
          'Accept': 'application/json, text/plain, text/html, */*',
        },
      });

      const contentType = resp.headers.get('content-type') || '';
      const status = resp.status;
      const statusText = resp.statusText;

      if (contentType.includes('application/json')) {
        const json = await resp.json();
        return {
          success: true,
          data: {
            url,
            status,
            contentType,
            payload: json,
          },
        };
      }

      let text = await resp.text();
      if (extractTextOnly && contentType.includes('text/html')) {
        // Strip scripts, styles, and tags for clean LLM context
        text = text
          .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
          .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
          .replace(/<[^>]+>/g, ' ')
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 5000);
      } else {
        text = text.slice(0, 5000);
      }

      return {
        success: true,
        data: {
          url,
          status,
          statusText,
          contentType,
          contentLength: text.length,
          preview: text,
        },
      };
    } catch (err: any) {
      return {
        success: false,
        data: null,
        error: `Failed to fetch '${url}': ${err.message}`,
      };
    }
  },
};
