import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(function (_a) {
    var mode = _a.mode;
    return ({
        plugins: [react()],
        server: {
            port: 5173,
            host: '127.0.0.1',
            proxy: {
                '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
                '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
                '/ws': { target: 'ws://127.0.0.1:8000', ws: true, changeOrigin: true },
            },
        },
        build: {
            outDir: 'dist',
            sourcemap: false,
            chunkSizeWarningLimit: 800,
            rollupOptions: {
                output: {
                    manualChunks: {
                        'vendor-react': ['react', 'react-dom'],
                        'vendor-icons': ['lucide-react'],
                        'vendor-markdown': ['react-markdown', 'remark-gfm'],
                    },
                },
            },
        },
        esbuild: {
            drop: mode === 'production' ? ['console', 'debugger'] : [],
        },
    });
});
