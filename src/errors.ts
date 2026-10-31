// The backend reports a failure as {error: code, message} (main.py answers_errors); these are its errors here.

export interface ErrorResponse {
    error: string;
    message: string;
}

// A failure the backend reported as {error, message}: the message is shown on the overlay
export class BackendError extends Error {}
export class NetworkError extends BackendError {}
export class ApiKeyError extends BackendError {}
export class RateLimitError extends BackendError {}
export class ModelNotAvailableError extends BackendError {}

function isErrorResponse(value: unknown): value is ErrorResponse {
    return typeof value === 'object' && value !== null && 'error' in value && 'message' in value;
}

// A backend reply that reports a failure ({error, message}) as the matching error; any other reply passes through
export function throwIfBackendError<T>(response: T | ErrorResponse): T {
    if (!isErrorResponse(response)) return response;
    switch (response.error) {
        case 'network_error': throw new NetworkError(response.message);
        case 'api_key_error': throw new ApiKeyError(response.message);
        case 'rate_limit_error': throw new RateLimitError(response.message);
        case 'model_not_available': throw new ModelNotAvailableError(response.message);
        default: throw new BackendError(response.message);  // ocr_failed, translation_failed
    }
}
