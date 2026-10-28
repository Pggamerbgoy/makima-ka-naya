import asyncio
from makima.tools.registry import get_registry
from makima.tools.selection import ToolSelectionService
from makima.config import get_settings

prompts = [
    ('01_calc_launch', 'Calculator khol do. Koi website search mat karna aur music ko touch mat karna.'),
    ('02_media_pause', 'Jo audio abhi chal rahi hai use pause karo. Player aur Brave ko close mat karna.'),
    ('03_calc_close', 'Sirf Calculator close karo. Music chalti rehni chahiye aur Brave ke existing tabs ko bilkul unchanged chhodna.'),
    ('04_focus_brave', 'Brave ki existing window ko saamne lao. Current tab ko change, reload, navigate ya close mat karna.'),
    ('05_fastembed_search', 'FastEmbed ki official documentation mein supported multilingual text-embedding models ke naam search karke 3 model names batao. Koi video ya music play mat karna.'),
    ('06_anime_miruro', 'Brave mein Miruro use karke Black Clover ki episode list kholo. YouTube AMV, edit, trailer, reaction, recap ya shorts nahi. Existing unrelated tabs ko close ya refresh mat karna.'),
    ('07_hinglish_pause', 'Bhai gaana pause kar de, lekin Brave ya music player band nahi hona chahiye.'),
    ('08_multi_tool', 'Calculator open karo aur abhi chal rahi media ka title aur playback status batao. Music pause, stop ya skip mat karna. Koi app close bhi mat karna.'),
    ('09_correction', 'Correction: music ko resume karo aur sirf Calculator close karo. Brave ko bilkul mat chhedna.'),
    ('10_disabled_tool', 'Calculator open karo, aur agar launch tool disabled hai toh usse bypass mat karna. Mujhe actual status batao.'),
    ('11_process_check', 'Check karo ki MakimaEvalProcess_7319 naam ka process run ho raha hai ya nahi. Koi process start, stop ya modify mat karna.'),
    ('12_ambiguity', 'Mere browser ka issue fix kar do.'),
    ('13_memory_fact', 'MEMORY.md mein QA Test category ke andar ye temporary fact save karo: Makima selector check = COBALT-17. Kisi existing fact ko edit ya delete mat karna, aur save result verify karna.'),
]

async def main():
    reg = get_registry(auto_discover=True)
    settings = get_settings()
    selector = ToolSelectionService(settings.tools.selection)
    schemas = reg.get_schemas()
    meta = {t.name: getattr(t, 'metadata', None) for t in reg.list_tools()}
    
    print(f'Total tools in catalogue: {len(schemas)}')
    for key, p in prompts:
        sel = await selector.select_schemas(schemas, p, tool_metadata=meta)
        names = [s.get('function', {}).get('name') for s in sel]
        print(f'[{key}] Selected {len(names)} tools: {names[:6]}')

if __name__ == '__main__':
    asyncio.run(main())
