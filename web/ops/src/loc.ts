/** Where an addressable object lives in the survey JSON (`osp_ops.doc.Loc`). */

import { toPointer, type PathPart } from './patch.ts';

export type Path = PathPart[];

export class Loc {
	constructor(
		readonly kind: string,
		readonly path: Path
	) {}
	get container(): Path {
		return this.path.slice(0, -1);
	}
	get index(): number {
		return this.path[this.path.length - 1] as number;
	}
	get pointer(): string {
		return toPointer(this.path);
	}
}
