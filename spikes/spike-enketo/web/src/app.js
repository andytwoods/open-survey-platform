// Spike participant runtime: enketo-core Form + our session glue (order application, autosave, submit).
import { Form } from 'enketo-core';
import $ from 'jquery';

const S = window.__SPIKE__;
const log = (window.__pageLog = []);

/** Reorder sibling elements so they appear in `names` order, keeping the slots they occupied. */
function reorder(elements, names, keyOf) {
    const byName = new Map(elements.map((el) => [keyOf(el), el]));
    const ordered = names.map((n) => byName.get(n)).filter(Boolean);
    if (ordered.length !== elements.length) return false;
    const marks = elements.map((el) => {
        const m = document.createComment('slot');
        el.replaceWith(m);
        return m;
    });
    marks.forEach((m, i) => m.replaceWith(ordered[i]));
    return true;
}

function applyOrders(formEl) {
    // E6 workaround: realised orders are computed by OUR server (Python PRNG) and stored in the
    // instance (order_att / order_blocks). Here we only apply them to the DOM before Form.init().
    if (S.orderAtt) {
        const group = formEl.querySelector('section[name="/data/p_att"]');
        const qs = [...group.querySelectorAll(':scope > .question')];
        reorder(qs, S.orderAtt.split(' '), (el) => el.querySelector('[name]').getAttribute('name').split('/').pop());
    }
    if (S.orderBlocks) {
        const names = S.orderBlocks.split(' ');
        // document order (the slots), then fill the slots in the realised order
        const blocks = [...formEl.querySelectorAll('section[name]')].filter((el) =>
            names.includes(el.getAttribute('name').split('/').pop())
        );
        reorder(blocks, names, (el) => el.getAttribute('name').split('/').pop());
    }
}

function currentPageName(form) {
    const cur = form.pages && form.pages.current;
    return cur ? cur.getAttribute('name') || cur.querySelector('[name]')?.getAttribute('name') : null;
}

async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
}

let saveTimer = null;
function saveDraft(form) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
        window.__draftPending = post(`/s/${S.sid}/draft`, { xml: form.getDataStr(), page: currentPageName(form) });
    }, 50);
}

function start() {
    const formEl = document.querySelector('form.or');
    applyOrders(formEl);
    const form = new Form(formEl, { modelStr: S.modelStr, instanceStr: S.instanceStr || null, submitted: false }, {});
    const errors = form.init();
    window.__form = form;
    window.__loadErrors = errors;
    formEl.addEventListener('pageflip', () => {
        // Lowering for semantics §3: clear values of non-relevant questions on every page change,
        // not only at final submit (Enketo's default).
        if (S.clearNonRelevantOnPage) form.clearNonRelevant();
        log.push(currentPageName(form));
        saveDraft(form);
    });
    formEl.addEventListener('change', () => saveDraft(form));
    formEl.addEventListener('input', () => saveDraft(form));
    if (S.page) {
        const target = formEl.querySelector(`[name="${S.page}"]`);
        if (target) form.pages.flipToPageContaining($(target));
    }
    if (!log.length) log.push(currentPageName(form));

    document.querySelector('#submit-form').addEventListener('click', async () => {
        const valid = await form.validate();
        if (!valid) {
            document.querySelector('#status').textContent = 'Please fix the highlighted answers.';
            return;
        }
        const res = await post(`/s/${S.sid}/submit`, {
            raw: form.getDataStr(),
            pruned: form.getDataStr({ irrelevant: false }),
            pages: log,
        });
        document.querySelector('.paper').innerHTML = `<h1 id="done">Thank you</h1><p>Saved ${res.file}</p>`;
    });
    document.body.dataset.ready = '1';
}

start();
