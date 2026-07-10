export function requestIsCurrent(currentPath, currentGeneration, requestPath, requestGeneration) {
  return currentPath === requestPath && currentGeneration === requestGeneration;
}

export function projectListRequestIsCurrent(
  latestRequestId,
  requestId,
  currentPath,
  currentGeneration,
  requestPath,
  requestGeneration,
) {
  if (latestRequestId !== requestId) {
    return false;
  }
  if (requestPath === null) {
    return true;
  }
  return requestIsCurrent(
    currentPath,
    currentGeneration,
    requestPath,
    requestGeneration,
  );
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}
