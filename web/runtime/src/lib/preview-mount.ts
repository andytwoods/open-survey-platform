/** What `App` takes in preview mode (task B11; built by `previewEnv` in `../preview.ts`). */
import type { Env, Session } from './session';

export interface PreviewMount {
	env: Env;
	slug: string;
	language?: string;
	/** Called with the session once it has booted. */
	onSession?: (s: Session) => void;
}
