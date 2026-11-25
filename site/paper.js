// Builds the practice paper PDF with jsPDF.
// Question images are 161 mm wide and sit beside a 13 mm question-number column; markscheme images are
// 174 mm wide (see scripts/build_bank.py). Images carry no question numbers: they are drawn here.
// All images are loaded through the loadImage(name) callback, which decrypts them (Vault.bytes).
'use strict';

const DTPaper = (() => {
  const PAGE_W = 210, LEFT = 18, NUM_W = 13, Q_X = LEFT + NUM_W, Q_W = 161, MS_X = LEFT, MS_W = 174;
  const TOP = 20, BOTTOM = 277, FOOTER_Y = 287;
  const MINUTES_PER_MARK = 1.8;
  const LEVELS = { SL: 'Standard level', HL: 'Higher level' };

  function duration(marks) {
    const total = Math.round(marks * MINUTES_PER_MARK);
    const h = Math.floor(total / 60), m = total % 60;
    const parts = [];
    if (h) parts.push(h + (h === 1 ? ' hour' : ' hours'));
    if (m || !h) parts.push(m + (m === 1 ? ' minute' : ' minutes'));
    return parts.join(' ');
  }

  // jsPDF's built-in fonts use the Windows-1252 character set; swap anything outside it.
  function safe(text) {
    return String(text)
      .replace(/[‐‑‒−]/g, '-')
      .replace(/[^\x00-\xff–—‘’“”•…€]/g, '?');
  }

  function cover(doc, opts, marks) {
    const level = LEVELS[opts.level] || opts.level;
    let y = 34;
    doc.setFont('helvetica', 'bold'); doc.setFontSize(22);
    doc.text('Design technology', LEFT, y); y += 10;
    doc.setFont('helvetica', 'normal'); doc.setFontSize(15);
    doc.text(level, LEFT, y); y += 8;
    doc.text('Paper ' + opts.paper, LEFT, y); y += 8;
    doc.text('Practice paper', LEFT, y); y += 14;
    doc.setFontSize(12);
    doc.text(duration(marks), LEFT, y); y += 16;

    // Candidate name box
    doc.setFontSize(10); doc.text('Candidate name', LEFT, y); y += 2;
    doc.setLineWidth(0.4); doc.rect(LEFT, y, PAGE_W - 2 * LEFT, 12); y += 26;

    doc.setFont('helvetica', 'bold'); doc.setFontSize(11);
    doc.text('Instructions to candidates', LEFT, y); y += 7;
    doc.setFont('helvetica', 'normal');
    const items = [
      'Do not open this examination paper until instructed to do so.',
      'Answer all questions.',
      'Answers must be written within the answer boxes provided.',
      'A calculator is permitted for this paper.',
      `The maximum mark for the examination paper is [${marks} marks].`,
    ];
    for (const t of items) {
      doc.text('•', LEFT + 1, y);
      doc.text(t, LEFT + 6, y);
      y += 6.5;
    }
    y += 10;
    doc.setFontSize(8.5); doc.setTextColor(90);
    const note = 'Practice paper written for teaching purposes in the format of the specimen papers for first ' +
                 'assessment 2027. Not an official IB publication.';
    doc.text(doc.splitTextToSize(note, PAGE_W - 2 * LEFT), LEFT, y);
    doc.setTextColor(0);
  }

  function footer(doc, pageNo, turnOver) {
    doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(0);
    doc.text('– ' + pageNo + ' –', PAGE_W / 2, FOOTER_Y, { align: 'center' });
    if (turnOver) {
      doc.setFont('helvetica', 'bold');
      doc.text('Turn over', PAGE_W - LEFT, FOOTER_Y, { align: 'right' });
    }
  }

  // Scale a {w_mm, h_mm} image to the given width.
  const fit = (img, width) => ({ w: width, h: img.h_mm * width / img.w_mm });

  /**
   * opts: {questions: [question objects, in paper order], level, paper, markscheme: bool,
   *        loadImage: name => Promise<Uint8Array>, onProgress: (done, total) => void}
   * Returns a jsPDF document.
   */
  async function build(opts) {
    const { jsPDF } = window.jspdf;
    const qs = opts.questions;
    const marks = qs.reduce((s, q) => s + q.marks, 0);
    const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true });
    doc.setProperties({ title: `Design technology ${opts.level} Paper ${opts.paper} practice paper`,
                        creator: 'DT practice-paper builder' });

    // Load (decrypt) every image first, in parallel.
    const names = qs.flatMap(q => q.pages.concat(opts.markscheme ? q.ms : []).map(p => p.image));
    let done = 0;
    const images = new Map(await Promise.all(names.map(async n => {
      const b = await opts.loadImage(n);
      if (opts.onProgress) opts.onProgress(++done, names.length);
      return [n, b];
    })));
    const draw = (p, x, y, w, h) => doc.addImage(images.get(p.image), 'PNG', x, y, w, h, p.image, 'FAST');

    // Cover
    cover(doc, opts, marks);

    // Questions: each starts on a new page.
    qs.forEach((q, i) => {
      doc.addPage();
      let y = TOP;
      doc.setFont('helvetica', 'bold'); doc.setFontSize(12);
      doc.text(String(i + 1) + '.', LEFT, y + 4.2);
      q.pages.forEach((p, k) => {
        const { w, h } = fit(p, Q_W);
        if (k > 0 && y + h > BOTTOM) { doc.addPage(); y = TOP; }
        draw(p, Q_X, y, w, h);
        y += h + 2;
      });
    });
    const lastPaperPage = doc.getNumberOfPages();

    // Markscheme
    if (opts.markscheme) {
      doc.addPage();
      let y = TOP + 4;
      doc.setFont('helvetica', 'bold'); doc.setFontSize(16);
      doc.text('Markscheme', LEFT, y); y += 6;
      doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(90);
      doc.text(`Design technology – ${LEVELS[opts.level] || opts.level} – Paper ${opts.paper} – ` +
               `practice paper (${marks} marks)`, LEFT, y);
      doc.setTextColor(0); y += 10;
      qs.forEach((q, i) => {
        const first = q.ms[0] ? fit(q.ms[0], MS_W).h : 0;
        if (y + 9 + first > BOTTOM) { doc.addPage(); y = TOP; }
        doc.setFont('helvetica', 'bold'); doc.setFontSize(12);
        doc.text(safe(`Question ${i + 1}: ${q.title}`), LEFT, y + 4.2);
        y += 8;
        if (!q.ms.length) {
          doc.setFont('helvetica', 'italic'); doc.setFontSize(10);
          doc.text('No markscheme available for this question.', LEFT, y + 4); y += 10;
        }
        q.ms.forEach((p, k) => {
          const { w, h } = fit(p, MS_W);
          if (k > 0 && y + h > BOTTOM) { doc.addPage(); y = TOP; }
          draw(p, MS_X, y, w, h);
          y += h + 6;
        });
      });
    }

    // Footers: number every page after the cover; "Turn over" on every question-paper page but the last.
    const n = doc.getNumberOfPages();
    for (let p = 1; p <= n; p++) {
      doc.setPage(p);
      const turnOver = p < lastPaperPage;
      if (p === 1) {
        doc.setFont('helvetica', 'bold'); doc.setFontSize(9);
        doc.text('Turn over', PAGE_W - LEFT, FOOTER_Y, { align: 'right' });
      } else {
        footer(doc, p, turnOver);
      }
    }
    return doc;
  }

  const fileName = (opts, marks) =>
    `DT_${opts.level}_Paper${opts.paper}_practice_${marks}marks.pdf`;

  return { build, duration, fileName, MINUTES_PER_MARK };
})();
