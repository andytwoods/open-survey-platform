// The demo builder's one entry (task DEMO2): which page this HTML file is comes from its
// `<meta name="osp-demo-page">`; the page module loads on demand, then boots on the
// in-memory backend (src/lib/demo/boot.ts).
import './demo.css';
import { bootDemo, type DemoPage } from '#lib/demo/boot.js';
import type { MountPage } from '#lib/host/mount.js';

const PAGES: Record<DemoPage, () => Promise<{ mount: MountPage }>> = {
	editor: () => import('../src/pages/editor.ts'),
	flow: () => import('../src/pages/flow.ts'),
	settings: () => import('../src/pages/settings.ts'),
	appearance: () => import('../src/pages/appearance.ts'),
	list: () => import('../src/pages/list.ts'),
	themes: () => import('../src/pages/themes.ts')
};

const name = document.querySelector<HTMLMetaElement>('meta[name="osp-demo-page"]')?.content as DemoPage | undefined;
const load = name && Object.hasOwn(PAGES, name) ? PAGES[name] : PAGES.editor;
void load().then(({ mount }) => bootDemo(name ?? 'editor', mount));
