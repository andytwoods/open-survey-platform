/** Requests from shell commands (palette) to the flow view, which may not be mounted. */
export const flowUi = $state({ addRequests: 0, addBlockRequests: 0 });

export function requestAddNode() {
	flowUi.addRequests++;
}

/** "Add block" (B20) from the palette while the Flow view is open. */
export function requestAddBlock() {
	flowUi.addBlockRequests++;
}
