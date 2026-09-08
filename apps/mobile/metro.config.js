/**
 * Metro, told about the monorepo.
 *
 * Expo's default config assumes the app owns its `node_modules`. In a pnpm workspace it
 * does not: `@sarana/ui` and `@sarana/ts-shared` are symlinks into `packages/`, and their
 * own dependencies are hoisted to the repo root. Without the two lines below, Metro
 * either cannot see the workspace sources or resolves two copies of React - which fails
 * at run time with an "invalid hook call" that points at the wrong file.
 */

const path = require('node:path');
const { getDefaultConfig } = require('expo/metro-config');

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, '../..');

const config = getDefaultConfig(projectRoot);

// Watch the workspace, so an edit to a token in packages/ui reloads the app.
config.watchFolders = [workspaceRoot];

// App-local first, then the hoisted root. pnpm's nested store is reached through the
// symlinks Metro already follows.
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(workspaceRoot, 'node_modules'),
];

// One React, one react-native. Two copies is the failure that costs an afternoon.
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
