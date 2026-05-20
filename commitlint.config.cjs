/**
 * Conventional Commits, with milestone scopes (m0..m6) reserved for milestone-closing commits.
 * Other scopes are free-form so day-to-day commits stay lightweight.
 */
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'chore',
        'docs',
        'refactor',
        'test',
        'ci',
        'build',
        'perf',
        'style',
        'revert',
      ],
    ],
    'subject-case': [2, 'always', 'lower-case'],
    'subject-full-stop': [2, 'never', '.'],
    'subject-empty': [2, 'never'],
    'header-max-length': [2, 'always', 72],
  },
};
