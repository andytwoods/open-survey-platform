/** Requests from shell commands (palette) to the flow view, which may not be mounted. */
export const flowUi = $state({ addRequests: 0 });

export function requestAddNode() {
	flowUi.addRequests++;
}
