#!/usr/bin/env node
// PreToolUse gate: a `git commit` is blocked until the code-review agent has signed off on this
// exact staged tree. The agent records approval by writing `git write-tree` to .claude/.review-state.
//
// Fails open on every unexpected condition. A gate that wedges the workflow when git or the hook
// payload misbehaves would be worse than no gate at all.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const ALLOW = 0;
const BLOCK = 2;

// `commit(?![-\w])` so `git commit-tree` and `git commit_foo` do not match. Each flag may carry a
// separate argument (`git -C path commit`, `git -c k=v commit`) — the canonical monorepo invocation.
// `-[^\s]+` covers `--flags` too; `--?` would parse them two ways — exponential backtracking.
const GIT_COMMIT = /\bgit\s+(?:-[^\s]+(?:\s+[^\s-][^\s]*)?\s+)*commit(?![-\w])/;

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function git(args) {
  return execFileSync('git', args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
}

function main() {
  const raw = readStdin();
  if (!raw) return ALLOW;

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return ALLOW;
  }

  if (payload?.tool_name !== 'Bash') return ALLOW;
  const command = payload?.tool_input?.command;
  if (typeof command !== 'string' || !GIT_COMMIT.test(command)) return ALLOW;

  let stagedTree;
  try {
    stagedTree = git(['write-tree']);
  } catch {
    return ALLOW;
  }
  if (!stagedTree) return ALLOW;

  let approved = '';
  try {
    approved = readFileSync('.claude/.review-state', 'utf8').trim();
  } catch {
    approved = '';
  }

  if (approved === stagedTree) return ALLOW;

  process.stderr.write(
    'This staged tree has not been reviewed.\n\n' +
      'Run the code-review subagent over `git diff --cached`, fix every blocking finding, and let it ' +
      'record approval. Then retry the commit.\n\n' +
      `Staged tree: ${stagedTree}\n` +
      `Last approved: ${approved || '(none)'}\n`,
  );
  return BLOCK;
}

process.exit(main());
