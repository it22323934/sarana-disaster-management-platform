/**
 * Domain rules shared by more than one surface.
 *
 * Everything here is a mirror of a rule the Python services own and enforce. It lives in
 * TypeScript because a surface needs to know the answer before the server does - an
 * operator deciding whether to send now, a handset deciding whether to make a noise - and
 * it lives in one place because the alternative is the same rule written three times and
 * wrong in one of them.
 */

export * from './quiet-hours.js';
