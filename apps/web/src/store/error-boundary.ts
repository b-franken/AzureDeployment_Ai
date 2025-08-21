export function withErrorHandling<T>(fn: () => Promise<T>): Promise<T> {
    try {
        return fn();
    } catch (error) {
        throw error;
    }
}