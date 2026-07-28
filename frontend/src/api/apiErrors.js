/**
 * apiErrors.js
 * ------------
 * Utilities for extracting human-readable error messages from API responses.
 *
 * FastAPI returns validation errors (HTTP 422) as:
 *   { detail: [ { loc: [...], msg: "...", type: "..." }, ... ] }
 *
 * FastAPI returns application errors (HTTP 400/403/404/500) as:
 *   { detail: "Some string message" }
 *
 * Without this helper, passing `e.response.data.detail` (an array) directly
 * into React state and then rendering it as a string causes:
 *   "Objects are not valid as a React child"
 */

/**
 * Extract a display-safe error string from an Axios error.
 *
 * @param {unknown} e         - The caught error (typically an Axios error).
 * @param {string}  fallback  - Message to show when nothing better is available.
 * @returns {string}
 */
export function extractApiError(e, fallback = 'An unexpected error occurred.') {
  const detail = e?.response?.data?.detail;

  // FastAPI 422 — detail is an array of validation error objects
  if (Array.isArray(detail)) {
    const messages = detail
      .map((err) => {
        // err.msg is the human-readable part, e.g. "String should have at least 5 characters"
        const field = err.loc?.slice(1).join(' → ') || '';   // skip "body" prefix
        const msg   = err.msg || 'Validation error';
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    return messages.length > 0 ? messages.join('; ') : fallback;
  }

  // FastAPI 400/403/404/500 — detail is a plain string
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  // Axios network error or unknown shape
  if (typeof e?.message === 'string' && e.message.trim()) {
    return e.message.trim();
  }

  return fallback;
}
