import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins:[react()], build:{rollupOptions:{output:{manualChunks:{charts:['echarts/core','echarts/charts','echarts/components','echarts/renderers'],markdown:['react-markdown']}}}},server:{proxy:{'/api':'http://127.0.0.1:8201','/portal':'http://127.0.0.1:8202'}} });
