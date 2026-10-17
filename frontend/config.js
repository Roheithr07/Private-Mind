/**
 * PrivateMind Deployment Configuration
 *
 * In local development, leave window.API_BASE_URL empty to connect to http://127.0.0.1:8000
 * When deploying to Render, set window.API_BASE_URL to your Render Web Service URL:
 * e.g. window.API_BASE_URL = 'https://privatemind-backend.onrender.com';
 */
if (typeof window !== 'undefined' && window.location && window.location.hostname && window.location.hostname.includes('onrender.com')) {
  window.API_BASE_URL = window.API_BASE_URL || 'https://privatemind-backend.onrender.com';
} else {
  window.API_BASE_URL = window.API_BASE_URL || '';
}
