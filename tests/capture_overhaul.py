"""Reproducible real-app screenshot pass. Creates scripted cases, makes no model calls."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect
import argparse
from urllib.request import urlopen
parser=argparse.ArgumentParser(description="Capture the integrated worker UI against an offline server.")
parser.add_argument("--base-url",default="http://127.0.0.1:8040")
parser.add_argument("--output",default="docs/screenshots/terry-overhaul")
parser.add_argument("--log",default="test-results/overhaul-integrated-screenshots.json")
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
  T=lambda n:f'[data-testid={n}]'
  def review_ready():
   expect(pg.locator(T('case-state'))).to_have_text('Awaiting review',timeout=45000)
   pg.wait_for_function("""()=>{if(document.querySelector('[data-testid="inv-findings"]'))return true;document.querySelector('[data-testid="btn-skip"]:not(:disabled)')?.click();return false}""",timeout=45000)
  def details():
   link=pg.locator(T('btn-inv-details'));link.wait_for()
   if link.get_attribute('aria-expanded')!='true': link.click()
  def lab_details():
   pg.locator(T('nav-lab')).click()
   if not pg.locator('.lab-details[open]').count(): pg.locator('.lab-details > summary').click()
  pg.goto(base);pg.locator(T('btn-lab-run')).wait_for();shot('01-lab',width<760)
  # The real offline agent fixture, never a substituted live result.
  pg.get_by_role('radiogroup',name='Investigation mode').get_by_role('radio',name='Specialists',exact=True).click()
  pg.locator(T('btn-lab-run')).click()
  # A lab run stays on Lab and plays the sandbox stage; only "Open investigation" changes workspace.
  opener=pg.locator(T('btn-open-investigation'));opener.wait_for(timeout=45000)
  if pg.locator(T('sandbox-stage')+'[data-stage="playing"]').count() and pg.locator(T('btn-stage-skip')).count(): pg.locator(T('btn-stage-skip')).click()
  shot('01b-sandbox-stage',width<760)
  opener.click();review_ready()
  root=pg.url.split('case=')[1]
  shot('02-investigation',width<760)
  pg.locator(T('inv-more')+' > summary').click()
  expect(pg.locator(T('compare-row-retained')).first).to_be_visible()
  if width >= 1280:
   row=pg.locator(T('compare-row-retained')).first.bounding_box()
   assert row['y']+row['height'] <= pg.locator(T('question-composer')).bounding_box()['y'], "Discrepancy is hidden by the question panel"
  shot('02b-more-tools',width<760)
  pg.locator(T('inv-findings')+' [data-testid^=chip-]').first.click();expect(pg.locator(T('raw-focus-line'))).to_be_visible();shot('03-evidence-inspector');pg.keyboard.press('Escape')
  details();pg.locator(T('inv-activity')+' .investigation-tools').get_by_role('button',name='Trace',exact=True).click();expect(pg.locator('.trace-events li[data-kind=delegation]')).to_have_count(2);pg.locator('.trace-events li[data-kind=tool] summary').first.click();shot('04-trace');pg.keyboard.press('Escape')
  lab_details();expect(pg.locator('.worker-cards article')).to_have_count(3);shot('08-workers',width<760)
  pg.get_by_role('button',name='Open worker record',exact=False).first.click();expect(pg.locator(T('raw-focus-line'))).to_be_visible();shot('09-worker-proof');pg.keyboard.press('Escape')
  pg.locator(T('tab-case')).click();pg.locator(T('btn-accept')).click();expect(pg.locator(T('case-state'))).to_have_text('Report locked');shot('05-locked-review',width<760)
  lab_details();pg.locator(T('btn-operator-record')).click();pg.locator(T('operator-record')).wait_for();shot('10-operator-history');pg.keyboard.press('Escape')
  pg.locator(T('tab-benchmark')).click();panel=pg.locator(T('lab-experiments'));panel.get_by_label('Investigator request allowance',exact=True).fill('4');panel.locator(T('btn-lab-compare')).click();pg.wait_for_function('old=>!location.hash.endsWith(old)',arg=root);review_ready()
  budget=pg.url.split('case=')[1]
  # A new execution is refused until every report of the experiment is locked, so lock this one in the UI first.
  pg.locator(T('btn-accept')).click();expect(pg.locator(T('case-state'))).to_have_text('Report locked')
  pg.locator(T('tab-benchmark')).click();panel.get_by_label('Starting worker run',exact=True).select_option(root);panel.get_by_label('Variable to change',exact=True).select_option('rogue_permissions');panel.get_by_label('New permission profile',exact=True).select_option('export_only');panel.locator(T('btn-lab-compare')).click();pg.wait_for_function('old=>!location.hash.endsWith(old)',arg=budget);review_ready()
  pg.locator(T('tab-benchmark')).click();expect(pg.locator(T('lab-comparison-table')+' tbody tr')).to_have_count(3);shot('06-experiments',width<760)
  pg.locator('[data-testid=btn-command]').click();pg.get_by_role('combobox',name='Search cases and actions').fill('Open Cases');shot('07-command');ctx.close()
 b.close()
Path(args.log).parent.mkdir(parents=True,exist_ok=True);Path(args.log).write_text(json.dumps(log,indent=2)+'\n')
print(json.dumps({'screenshots':len(log),'page_overflow':sum(x['page_horizontal_overflow'] for x in log),'page_errors':sum(len(x['errors']) for x in log)}))
