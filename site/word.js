// Builds the practice paper as a Word document (.docx) with the docx library (site/vendor/docx.iife.js).
// Same content as paper.js: cover page, each question on a new page as its page images beside a question
// number, then the optional markscheme. The question text is in the images, so it can't be edited, but
// staff can add their own text, reorder pages or open the file in Google Docs.
'use strict';

const DTWord = (() => {
  const LIB = 'vendor/docx.iife.js';
  const NUM_W = 13, Q_W = 161, MS_W = 174;          // mm, as in paper.js
  const LEVELS = { SL: 'Standard level', HL: 'Higher level' };
  let loading = null;

  // Load the (large) docx library only when a Word file is first asked for.
  function load() {
    if (window.docx) return Promise.resolve(window.docx);
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = LIB;
        s.onload = () => (window.docx ? resolve(window.docx) : reject(new Error('Word library did not load')));
        s.onerror = () => { loading = null; reject(new Error('Could not load the Word library. Check the connection and try again.')); };
        document.head.append(s);
      });
    }
    return loading;
  }

  /**
   * opts: {questions, level, paper, markscheme: bool, loadImage: name => Promise<Uint8Array>,
   *        onProgress: (done, total) => void}
   * Returns a Promise<Blob> holding the .docx file.
   */
  async function build(opts) {
    const d = await load();
    const twip = mm => d.convertMillimetersToTwip(mm);
    const px = mm => Math.round(mm * 96 / 25.4);           // image sizes are given in pixels at 96 dpi
    const qs = opts.questions;
    const marks = qs.reduce((s, q) => s + q.marks, 0);
    const level = LEVELS[opts.level] || opts.level;

    const names = qs.flatMap(q => q.pages.concat(opts.markscheme ? q.ms : []).map(p => p.image));
    let done = 0;
    const images = new Map(await Promise.all(names.map(async n => {
      const b = await opts.loadImage(n);
      if (opts.onProgress) opts.onProgress(++done, names.length);
      return [n, b];
    })));

    const text = (t, o = {}) => new d.TextRun({ text: t, ...o });
    const para = (children, o = {}) => new d.Paragraph({ children: [].concat(children), spacing: { before: 0, after: 0 }, ...o });
    const gap = (pt = 6) => para([], { spacing: { before: 0, after: pt * 20 } });
    const image = (p, width) => para(new d.ImageRun({
      type: 'png', data: images.get(p.image),
      transformation: { width: px(width), height: px(p.h_mm * width / p.w_mm) },
    }), { spacing: { before: 0, after: 80 } });
    const none = { style: d.BorderStyle.NONE, size: 0, color: 'FFFFFF' };
    const noBorders = { top: none, bottom: none, left: none, right: none, insideHorizontal: none, insideVertical: none };
    const line = { style: d.BorderStyle.SINGLE, size: 6, color: '000000' };

    // ---- Cover
    const children = [
      gap(40),
      para(text('Design technology', { bold: true, size: 44 }), { spacing: { after: 160 } }),
      para(text(level, { size: 30 }), { spacing: { after: 100 } }),
      para(text('Paper ' + opts.paper, { size: 30 }), { spacing: { after: 100 } }),
      para(text('Practice paper', { size: 30 }), { spacing: { after: 280 } }),
      para(text(DTPaper.duration(marks), { size: 24 }), { spacing: { after: 400 } }),
      para(text('Candidate name', { size: 20 }), { spacing: { after: 60 } }),
      new d.Table({
        width: { size: twip(174), type: d.WidthType.DXA }, columnWidths: [twip(174)],
        borders: { top: line, bottom: line, left: line, right: line },
        rows: [new d.TableRow({ height: { value: twip(12), rule: d.HeightRule.EXACT },
                                children: [new d.TableCell({ children: [para([])] })] })],
      }),
      gap(30),
      para(text('Instructions to candidates', { bold: true, size: 22 }), { spacing: { after: 140 } }),
      ...['Do not open this examination paper until instructed to do so.',
          'Answer all questions.',
          'Answers must be written within the answer boxes provided.',
          'A calculator is permitted for this paper.',
          `The maximum mark for the examination paper is [${marks} marks].`]
        .map(t => para(text(t, { size: 22 }), { bullet: { level: 0 }, spacing: { after: 100 } })),
      gap(24),
      para(text('Practice paper written for teaching purposes in the format of the specimen papers for first ' +
                'assessment 2027. Not an official IB publication.', { size: 17, color: '5A5A5A' })),
    ];

    // ---- Questions: each on a new page, number in a 13 mm column beside the page images.
    qs.forEach((q, i) => {
      children.push(para([], { pageBreakBefore: true }));
      children.push(new d.Table({
        width: { size: twip(NUM_W + Q_W), type: d.WidthType.DXA },
        columnWidths: [twip(NUM_W), twip(Q_W)],
        borders: noBorders,
        rows: [new d.TableRow({ cantSplit: false, children: [
          new d.TableCell({ width: { size: twip(NUM_W), type: d.WidthType.DXA }, borders: noBorders,
                            margins: { top: 0, bottom: 0, left: 0, right: 0 },
                            children: [para(text(`${i + 1}.`, { bold: true, size: 24 }))] }),
          new d.TableCell({ width: { size: twip(Q_W), type: d.WidthType.DXA }, borders: noBorders,
                            margins: { top: 0, bottom: 0, left: 0, right: 0 },
                            children: q.pages.map(p => image(p, Q_W)) }),
        ] })],
      }));
    });

    // ---- Markscheme
    if (opts.markscheme) {
      children.push(para(text('Markscheme', { bold: true, size: 32 }), { pageBreakBefore: true, spacing: { after: 80 } }));
      children.push(para(text(`Design technology – ${level} – Paper ${opts.paper} – practice paper ` +
                              `(${marks} marks)`, { size: 18, color: '5A5A5A' }), { spacing: { after: 240 } }));
      qs.forEach((q, i) => {
        children.push(para(text(`Question ${i + 1}: ${q.title}`, { bold: true, size: 24 }),
                           { keepNext: true, spacing: { before: i ? 240 : 0, after: 120 } }));
        if (!q.ms.length) children.push(para(text('No markscheme available for this question.', { italics: true })));
        q.ms.forEach(p => children.push(image(p, MS_W)));
      });
    }

    const pageNumber = new d.Footer({ children: [para(
      [text('– ', { size: 18 }), new d.TextRun({ children: [d.PageNumber.CURRENT], size: 18 }), text(' –', { size: 18 })],
      { alignment: d.AlignmentType.CENTER })] });
    const doc = new d.Document({
      creator: 'DT practice-paper builder',
      title: `Design technology ${opts.level} Paper ${opts.paper} practice paper`,
      styles: { default: { document: { run: { font: 'Arial', size: 22 } } } },
      sections: [{
        properties: {
          titlePage: true,                                   // no page number on the cover
          page: { size: { width: twip(210), height: twip(297) },
                  margin: { top: twip(15), bottom: twip(18), left: twip(18), right: twip(18),
                            header: twip(8), footer: twip(8) } },
        },
        footers: { default: pageNumber, first: new d.Footer({ children: [para([])] }) },
        children,
      }],
    });
    return d.Packer.toBlob(doc);
  }

  const fileName = (opts, marks) => `DT_${opts.level}_Paper${opts.paper}_practice_${marks}marks.docx`;

  return { build, fileName, load };
})();
