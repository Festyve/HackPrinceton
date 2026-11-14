"""Reproducible real-app screenshot pass. Creates scripted cases, makes no model calls."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect
import argparse
from urllib.request import urlopen
parser=argparse.ArgumentParser(description="Capture the integrated worker UI against an offline server.")
parser.add_argument("--base-url",default="http://127.0.0.1:8040")
parser.add_argument("--output",default="docs/screenshots/terry-overhaul")
args=parser.parse_args()
base=args.base_url.rstrip("/")
with urlopen(base + "/api/runtime") as response:
 runtime=json.load(response)
assert runtime["live_inference"] == "BLOCKED", "Start an offline server before running this capture."
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
log=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,channel='chrome')
 for width,height in [(1440,900),(1280,720),(390,844)]:
  ctx=b.new_context(viewport={'width':width,'height':height},reduced_motion='reduce');pg=ctx.new_page();errors=[]
  pg.on('pageerror',lambda e:errors.append(str(e)))
  pg.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
  def shot(name,full=False):
   pg.screenshot(path=str(out/f'{name}-{width}x{height}.png'),full_page=full)
   log.append({'screen':name,'viewport':[width,height],'page_horizontal_overflow':pg.evaluate('document.documentElement.scrollWidth > innerWidth'),'errors':list(errors)})
  pg.goto(base);pg.locator('[data-testid=btn-lab-run]').wait_for();shot('01-lab',width<760)
  # The real offline agent fixture, never a substituted live result.
  pg.locator('.lab-overview .advanced-config summary').click();pg.get_by_label('Investigation mode',exact=True).select_option('specialist');pg.locator('.lab-overview .advanced-config summary').click()
  pg.locator('[data-testid=btn-lab-run]').click();expect(pg.locator('[data-testid=case-state]')).to_have_text('Awaiting review',timeout=45000)
  root=pg.url.split('case=')[1]
  expect(pg.locator('[data-testid=compare-row-retained]').first).to_be_visible()
  if width >= 1280:
   row=pg.locator('[data-testid=compare-row-retained]').first.bounding_box()
   assert row['y']+row['height'] <= pg.locator('[data-testid=question-composer]').bounding_box()['y'], "Discrepancy is hidden by the question panel"
  shot('02-investigation',width<760)
  pg.locator('[data-testid^=finding-] [data-testid^=chip-]').first.click();expect(pg.locator('[data-testid=raw-focus-line]')).to_be_visible();shot('03-evidence-inspector');pg.keyboard.press('Escape')
  pg.get_by_role('button',name='Trace',exact=True).click();expect(pg.locator('.trace-events li[data-kind=delegation]')).to_have_count(2);pg.locator('.trace-events li[data-kind=tool] summary').first.click();shot('04-trace');pg.keyboard.press('Escape')
  pg.locator('[data-testid=nav-lab]').click();expect(pg.locator('.worker-cards article')).to_have_count(3);shot('08-workers',width<760)
  pg.get_by_role('button',name='Open worker record',exact=False).first.click();expect(pg.locator('[data-testid=raw-focus-line]')).to_be_visible();shot('09-worker-proof');pg.keyboard.press('Escape')
  pg.locator('[data-testid=tab-case]').click();pg.locator('[data-testid=btn-accept]').click();expect(pg.locator('[data-testid=case-state]')).to_have_text('Report locked');shot('05-locked-review',width<760)
  pg.locator('[data-testid=nav-lab]').click();pg.locator('[data-testid=btn-operator-record]').click();pg.locator('[data-testid=operator-record]').wait_for();shot('10-operator-history');pg.keyboard.press('Escape')
  pg.locator('[data-testid=tab-benchmark]').click();panel=pg.locator('[data-testid=lab-experiments]');panel.locator('.comparison-options > summary').click();panel.get_by_label('Investigator request allowance',exact=True).fill('4');panel.locator('[data-testid=btn-lab-compare]').click();pg.wait_for_function('old=>!location.hash.endsWith(old)',arg=root);expect(pg.locator('[data-testid=case-state]')).to_have_text('Awaiting review',timeout=45000)
  budget=pg.url.split('case=')[1];pg.locator('[data-testid=tab-benchmark]').click();panel.get_by_label('Starting worker run',exact=True).select_option(root);panel.locator('.comparison-options > summary').click();panel.get_by_label('Variable to change',exact=True).select_option('rogue_permissions');panel.get_by_label('New permission profile',exact=True).select_option('export_only');panel.locator('[data-testid=btn-lab-compare]').click();pg.wait_for_function('old=>!location.hash.endsWith(old)',arg=budget);expect(pg.locator('[data-testid=case-state]')).to_have_text('Awaiting review',timeout=45000)
  pg.locator('[data-testid=tab-benchmark]').click();expect(pg.locator('[data-testid=lab-comparison-table] tbody tr')).to_have_count(3);shot('06-experiments',width<760)
  pg.locator('[data-testid=btn-command]').click();pg.get_by_role('combobox',name='Search cases and actions').fill('Open Cases');shot('07-command');ctx.close()
 b.close()
Path('test-results/overhaul-integrated-screenshots.json').write_text(json.dumps(log,indent=2)+'\n')
print(json.dumps({'screenshots':len(log),'page_overflow':sum(x['page_horizontal_overflow'] for x in log),'page_errors':sum(len(x['errors']) for x in log)}))
