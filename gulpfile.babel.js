import buildbranch from 'buildbranch';
import rimraf from 'rimraf';
import each from 'each-done';
import express from 'express';
import fs, { outputFile as output } from 'fs-extra';
import { html } from 'commonmark-helpers';
import numbers from 'typographic-numbers';
import numd from 'numd';
import { pipe, prop, head, splitEvery } from 'ramda';
import sequence from 'run-sequence';
import renderTweet from 'tweet.md';
import autoprefixer from 'autoprefixer';
import pcssImport from 'postcss-import';
import pcssInitial from 'postcss-initial';
import webpack from 'webpack';

import gulp, { dest, src, start as _start, task as _task } from 'gulp';
import gulpJade from 'gulp-jade';
import rename from 'gulp-rename';
import watch from 'gulp-watch';
import { log, PluginError } from 'gulp-util';
import jimp from 'gulp-jimp';
import postcss from 'gulp-postcss';

import articleData from 'article-data';
import { site } from './package.json';
import webpackConfig from './webpack.config.babel.js';

import authorRender from './helpers/author-render';
import bust from './helpers/bust';
import lastUpdated from './helpers/last-updated';

import authors from './dump';
const latestInfo = head(authors).info;

const start = _start.bind(gulp);
const task = _task.bind(gulp);

const jadeDefaults = {
  pretty: true,
  locals: {
    site,
    latestInfo,
    numbers: input => numbers(input, { locale: 'ru' }),
    people: numd('человек', 'человека', 'человек'),
  },
};

const getOptions = (opts = {}) =>
  Object.assign({}, jadeDefaults, opts, {
    locals: Object.assign({}, jadeDefaults.locals, opts.locals),
  });

const jade = opts => gulpJade(getOptions(opts));
const firstTweet = pipe(prop('tweets'), head);
const render = pipe(renderTweet, html);

/**
 * MAIN TASKS
 */
task('index', ['css'], () => {
  const authorsToPost = authors.filter(author => author.post !== false);
  return src('layouts/index.jade')
    .pipe(jade({
      locals: {
        title: `Сайт @${site.title}`,
        desc: site.description,
        currentAuthor: head(authors),
        authors: authorsToPost,
        helpers: { authorRender, bust },
      },
    }))
    .pipe(rename({ basename: 'index' }))
    .pipe(dest('dist'));
});

task('authoring', ['css'], () => {
  const readme = fs.readFileSync('./pages/authoring.md', { encoding: 'utf8' });
  const article = articleData(readme, 'D MMMM YYYY', 'en'); // TODO change to 'ru' after moment/moment#2634 will be published
  return src('layouts/article.jade')
    .pipe(jade({
      locals: Object.assign({}, article, {
        title: 'Авторам',
        url: 'authoring/',
        helpers: { bust },
      }),
    }))
    .pipe(rename({ dirname: 'authoring' }))
    .pipe(rename({ basename: 'index' }))
    .pipe(dest('dist'));
});

task('authors', ['css'], done => {
  const authorsToPost = authors.filter(author => author.post !== false);
  each(authorsToPost, author => {
    return src('./layouts/author.jade')
      .pipe(jade({
        pretty: true,
        locals: {
          title: `Неделя @${author.username} в @${site.title}`,
          author,
          helpers: { authorRender, bust },
        },
      }))
      .pipe(rename({ dirname: author.username }))
      .pipe(rename({ basename: 'index' }))
      .pipe(dest('dist'));
  }, done);
});

task('userpics', () =>
  src('dump/images/*-image*')
    .pipe(jimp({ resize: { width: 192, height: 192 }}))
    .pipe(dest('dist/images')));

task('banners', () =>
  src('dump/images/*-banner*')
    .pipe(dest('dist/images')));

task('current-userpic', () =>
  src(`dump/images/${head(authors).username}-image*`)
    .pipe(jimp({ resize: { width: 192, height: 192 }}))
    .pipe(rename('current-image'))
    .pipe(dest('dist/images')));

task('current-banner', () =>
  src(`dump/images/${head(authors).username}-banner*`)
    .pipe(rename('current-banner'))
    .pipe(dest('dist/images')));

task('current-media', ['current-userpic', 'current-banner']);

task('css', () =>
  src('css/styles.css')
    .pipe(postcss([
      pcssImport,
      pcssInitial,
      autoprefixer,
    ]))
    .pipe(dest('dist/css')));

task('js', done => {
  webpack(webpackConfig, (err, ) => {
    if (err) throw new PluginError('webpack', err);
    done();
  });
});

task('static', () =>
  src([
    'static/**',
    'static/.**',
    'node_modules/bootstrap/dist/**',
  ]).pipe(dest('dist')));

task('server', () => {
  const app = express();
  app.use(express.static('dist'));
  app.listen(4000);
  log('Server is running on http://localhost:4000');
});

/**
 * FLOW
 */
task('clean', done => rimraf('dist', done));

task('html', ['authors', 'index', 'authoring', ]);
task('build', done => sequence( 'css', 'js', 'static', 'html', 'userpics', 'banners', 'current-media', done));

task('default', done => sequence('clean', 'watch', done));

task('watch', ['server', 'build'], () => {
  watch(['**/*.jade'], () => start('html'));
  watch(['css/**/*.css'], () => start('css'));
  watch('js/**/*.js', () => start('js'));
  watch('static/**', () => start('static'));
});

task('deploy', ['build'], done =>
  buildbranch({ branch: 'gh-pages', folder: 'dist' }, done));
