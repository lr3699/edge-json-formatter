/**
 * CodeMirror 6 打包入口 —— 供 tools/build-vendor.js 用 esbuild 打成单文件 IIFE。
 *
 * 为什么要这一步：CM6 是 ESM 多包结构（state/view/language/lezer/…），
 * 浏览器直接 <script> 加载不了裸模块名；而扩展的 MV3 又禁止远程代码，
 * 所以必须本地打成自包含 bundle。产物提交进仓库（src/vendor/），
 * 打包 zip 时随 src 一起进包，运行时零网络请求。
 *
 * 只导出真正用得到的部分，靠 esbuild 的 tree-shaking 把体积压下来。
 *
 * 注意用的是 minimalSetup 而不是 basicSetup：basicSetup 无条件带上行号槽与
 * 折叠槽，而本扩展的「显示行号」是用户设置项（默认关闭），大文档视图必须
 * 跟着设置走，所以行号槽由 bigview.js 用 Compartment 按需挂载。
 */
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { EditorState, Compartment } from '@codemirror/state';
import { minimalSetup } from 'codemirror';
import { json } from '@codemirror/lang-json';
import {
  HighlightStyle, syntaxHighlighting, codeFolding, foldGutter, foldKeymap,
  foldAll, unfoldAll, foldCode, unfoldCode, toggleFold, foldEffect,
} from '@codemirror/language';
import { search, searchKeymap, openSearchPanel, closeSearchPanel, findNext, findPrevious } from '@codemirror/search';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { tags as t } from '@lezer/highlight';

export {
  EditorView, EditorState, Compartment, minimalSetup, lineNumbers,
  keymap, json,
  HighlightStyle, syntaxHighlighting, codeFolding, foldGutter, foldKeymap,
  foldAll, unfoldAll, foldCode, unfoldCode, toggleFold, foldEffect,
  search, searchKeymap, openSearchPanel, closeSearchPanel, findNext, findPrevious,
  defaultKeymap, history, historyKeymap, indentWithTab,
  t as tags,
};
