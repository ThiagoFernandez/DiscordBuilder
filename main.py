import os
import sys
import discord
import json
import argparse
from dotenv import load_dotenv

parser = argparse.ArgumentParser(description="Arma un servidor de Discord desde un JSON.")
parser.add_argument("--dry-run", action="store_true", help="Imprime el plan sin tocar el servidor.")
parser.add_argument("--prune", action="store_true", help="Borra canales, categorías y roles que no estén en el JSON.")
args = parser.parse_args()

def get_server_config():
    with open("server.json", "r", encoding="utf-8") as f:
        return json.load(f)

def validar_json(config):
    """Valida la estructura del JSON antes de conectar el bot a Discord."""
    for i, rol in enumerate(config.get("roles", [])):
        if "name" not in rol:
            raise ValueError(f"Falta 'name' en el rol #{i+1}")
        for p in rol.get("permissions", {}):
            if p not in discord.Permissions.VALID_FLAGS:
                raise ValueError(f"Permiso inválido '{p}' en el rol '{rol['name']}'")

    for i, cat in enumerate(config.get("categories", [])):
        if "name" not in cat:
            raise ValueError(f"Falta 'name' en la categoría #{i+1}")

        for j, canal in enumerate(cat.get("channels", [])):
            if "name" not in canal:
                raise ValueError(f"Falta 'name' en un canal de la categoría '{cat['name']}'")
            if canal.get("type") not in ["text", "voice"]:
                raise ValueError(f"El canal '{canal.get('name')}' tiene un type inválido. Usa 'text' o 'voice'.")
            for permisos in canal.get("overwrites", {}).values():
                for p in permisos:
                    if p not in discord.PermissionOverwrite.VALID_NAMES:
                        raise ValueError(f"Permiso inválido '{p}' en el canal '{canal['name']}'")

def buscar_rol(guild, rol_nombre):
    if rol_nombre == "@everyone":
        return guild.default_role
    return discord.utils.get(guild.roles, name=rol_nombre)

def overwrites_de_canal(guild, base, canal_data):
    """Parte de los permisos de la categoría y les suma los del canal."""
    resultado = {obj: discord.PermissionOverwrite.from_pair(*ow.pair()) for obj, ow in base.items()}
    for rol_nombre, permisos in canal_data.get("overwrites", {}).items():
        rol_obj = buscar_rol(guild, rol_nombre)
        if rol_obj:
            resultado.setdefault(rol_obj, discord.PermissionOverwrite()).update(**permisos)
        else:
            print(f"   ⚠️ Advertencia: No se encontró el rol '{rol_nombre}' para permisos del canal '{canal_data['name']}'.")
    return resultado

def nombre_canal_discord(canal_data):
    """Nombre con el que Discord guarda el canal (los de texto se normalizan)."""
    if canal_data["type"] == "text":
        return canal_data["name"].lower().replace(" ", "-")
    return canal_data["name"]

async def borrar(objeto, descripcion):
    if args.dry_run:
        print(f" [DRY-RUN] Borraría {descripcion}.")
        return
    try:
        await objeto.delete(reason="DiscordBuilder --prune: no está en server.json")
        print(f" 🗑️ {descripcion} borrado.")
    except discord.HTTPException as e:
        # Discord no deja borrar algunas cosas (ej. canales obligatorios de Comunidad): sigo con el resto
        print(f" ⚠️ No se pudo borrar {descripcion}: {e}")

async def podar(guild, config):
    """Borra lo que está en el server y no en el JSON."""
    print("\n🧹 Podando lo que no está en el JSON...")
    categorias = {cat["name"]: {nombre_canal_discord(c) for c in cat.get("channels", [])}
                  for cat in config.get("categories", [])}

    for canal in list(guild.channels):
        if isinstance(canal, discord.CategoryChannel):
            continue
        nombre_cat = canal.category.name if canal.category else None
        if canal.name not in categorias.get(nombre_cat, set()):
            donde = f"en '{nombre_cat}'" if nombre_cat else "sin categoría"
            await borrar(canal, f"el canal '{canal.name}' ({donde})")

    for cat in list(guild.categories):
        if cat.name not in categorias:
            await borrar(cat, f"la categoría '{cat.name}'")

    # Nunca toco @everyone, roles de bots/integraciones ni roles que el bot no puede editar
    roles_json = {rol["name"] for rol in config.get("roles", [])}
    for rol in list(guild.roles):
        if rol.is_default() or rol.managed or rol >= guild.me.top_role:
            continue
        if rol.name not in roles_json:
            await borrar(rol, f"el rol '{rol.name}'")

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✅ Conectado exitosamente como {client.user}')

    # Validación segura fuera del try/finally para evitar el cuelgue infinito
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print(f"❌ Error: No se encontró el servidor con ID {GUILD_ID}.")
        await client.close()
        return

    print(f"\n=== CONSTRUYENDO SERVIDOR: {guild.name} ===")
    if args.dry_run:
        print("⚠️ MODO DRY-RUN ACTIVADO: No se harán cambios en el servidor.")

    try:
        print("\n⚙️ Procesando Roles...")
        for rol_data in config.get("roles", []):
            nombre_rol = rol_data["name"]
            rol_existente = discord.utils.get(guild.roles, name=nombre_rol)

            is_hoist = rol_data.get("hoist", False)
            color_val = rol_data.get("color", 0)
            if isinstance(color_val, str) and color_val.startswith("0x"):
                color_val = int(color_val, 16)

            permisos = None 
            if "permissions" in rol_data:
                permisos = discord.Permissions(**rol_data["permissions"])

            if rol_existente:
                if args.dry_run:
                    print(f" [DRY-RUN] Actualizaría el rol '{nombre_rol}'.")
                else:
                    if permisos is not None:
                        await rol_existente.edit(hoist=is_hoist, colour=discord.Colour(color_val), permissions=permisos)
                    else:
                        await rol_existente.edit(hoist=is_hoist, colour=discord.Colour(color_val))
                    print(f" - Rol '{nombre_rol}' ya existe (color/hoist/permisos actualizados).")
            else:
                if args.dry_run:
                    print(f" [DRY-RUN] Crearía el rol '{nombre_rol}'.")
                else:
                    await guild.create_role(
                        name=nombre_rol,
                        hoist=is_hoist,
                        colour=discord.Colour(color_val),
                        permissions=permisos or discord.Permissions.none()
                    )
                    print(f" ✅ Rol '{nombre_rol}' creado (hoist={is_hoist}, color={color_val}).")

        print("\n⚙️ Procesando Categorías y Canales...")
        for cat_data in config.get("categories", []):
            nombre_cat = cat_data["name"]

            overwrites_dict = {}
            if "overwrites" in cat_data:
                for rol_nombre, permisos in cat_data["overwrites"].items():
                    rol_obj = buscar_rol(guild, rol_nombre)

                    if rol_obj:
                        overwrites_dict[rol_obj] = discord.PermissionOverwrite(**permisos)
                    else:
                        print(f" ⚠️ Advertencia: No se encontró el rol '{rol_nombre}' para permisos.")

            cat_existente = discord.utils.get(guild.categories, name=nombre_cat)

            if not cat_existente:
                if args.dry_run:
                    print(f"\n📁 [DRY-RUN] Crearía la categoría '{nombre_cat}'.")
                else:
                    cat_existente = await guild.create_category(name=nombre_cat, overwrites=overwrites_dict)
                    print(f"\n📁 Categoría '{nombre_cat}' creada.")
            else:
                # Solo edito permisos si el JSON explícitamente pide controlarlos
                if "overwrites" in cat_data:
                    if args.dry_run:
                        print(f"\n📁 [DRY-RUN] Actualizaría permisos de la categoría '{nombre_cat}'.")
                    else:
                        await cat_existente.edit(overwrites=overwrites_dict)
                        print(f"\n📁 Categoría '{nombre_cat}' ya existe (permisos actualizados).")
                else:
                    print(f"\n📁 Categoría '{nombre_cat}' ya existe (sin cambios en permisos).")

            for canal_data in cat_data.get("channels", []):
                nombre_canal = canal_data["name"]
                tipo = canal_data["type"]

                canales_en_categoria = cat_existente.channels if cat_existente else []

                base = cat_existente.overwrites if cat_existente else overwrites_dict
                permisos_canal = overwrites_de_canal(guild, base, canal_data)

                if tipo == "text":
                    nombre_esperado = nombre_canal.lower().replace(" ", "-")
                    canal_existente = discord.utils.get(canales_en_categoria, name=nombre_esperado)

                    if not canal_existente:
                        if args.dry_run:
                            print(f"   💬 [DRY-RUN] Crearía canal de texto '{nombre_canal}'.")
                        else:
                            topic = canal_data.get("topic")
                            await guild.create_text_channel(name=nombre_canal, category=cat_existente, topic=topic, overwrites=permisos_canal)
                            print(f"   💬 Canal de texto '{nombre_canal}' creado.")
                    else:
                        print(f"   - Canal de texto '{nombre_esperado}' ya existe.")

                elif tipo == "voice":
                    nombre_esperado = nombre_canal
                    canal_existente = discord.utils.get(canales_en_categoria, name=nombre_esperado)

                    if not canal_existente:
                        if args.dry_run:
                            print(f"   🔊 [DRY-RUN] Crearía canal de voz '{nombre_canal}'.")
                        else:
                            limite_usuarios = canal_data.get("user_limit")
                            await guild.create_voice_channel(
                                name=nombre_canal,
                                category=cat_existente,
                                user_limit=limite_usuarios,
                                overwrites=permisos_canal
                            )
                            print(f"   🔊 Canal de voz '{nombre_canal}' creado.")
                    else:
                        print(f"   - Canal de voz '{nombre_esperado}' ya existe.")

                # Igual que en categorías: solo toco permisos si el canal los declara
                if canal_existente and "overwrites" in canal_data:
                    if args.dry_run:
                        print(f"     [DRY-RUN] Actualizaría permisos del canal '{nombre_esperado}'.")
                    else:
                        await canal_existente.edit(overwrites=permisos_canal)
                        print(f"     Permisos del canal '{nombre_esperado}' actualizados.")

        settings = config.get("server_settings")
        if settings:
            print("\n⚙️ Aplicando ajustes del servidor...")
            canal_sistema = discord.utils.get(guild.text_channels, name=settings.get("system_channel"))
            canal_afk = discord.utils.get(guild.voice_channels, name=settings.get("afk_channel"))
            timeout = settings.get("afk_timeout", 300)

            if args.dry_run:
                print(f" [DRY-RUN] Actualizaría ajustes: AFK={canal_afk}, System={canal_sistema}, Timeout={timeout}")
            else:
                await guild.edit(
                    system_channel=canal_sistema,
                    afk_channel=canal_afk,
                    afk_timeout=timeout
                )
                print(" ✅ Ajustes globales aplicados correctamente.")

        if args.prune:
            await podar(guild, config)

    except discord.Forbidden as e:
        print(f"\n❌ Error de Permisos (Forbidden): El bot no tiene permiso. Detalles: {e}")
    except discord.HTTPException as e:
        print(f"\n❌ Error de la API (HTTPException): Detalles: {e}")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
    finally:
        print(f"\n=== ESTRUCTURA DEL SERVIDOR: {guild.name} ===")
        print("\n👑 ROLES:")
        for role in reversed(guild.roles):
            print(f" - {role.name}")

        print("\n📁 CATEGORÍAS Y CANALES:")
        for category in guild.categories:
            print(f"\n[{category.name}]")
            for channel in category.channels:
                if isinstance(channel, discord.TextChannel):
                    print(f"  💬 {channel.name}")
                elif isinstance(channel, discord.VoiceChannel):
                    print(f"  🔊 {channel.name}")

        print("\nLectura finalizada. Desconectando...")
        await client.close()


if __name__ == '__main__':
    try:
        # Validación temprana ANTES de conectarse
        config = get_server_config()
        validar_json(config)

        client.run(TOKEN)
    except ValueError as ve:
        print(f"❌ Error en server.json: {ve}")
        sys.exit(1)
    except discord.LoginFailure:
        print("❌ Error crítico: Token inválido - Revisá tu archivo .env")
    except Exception as e:
        print(f"❌ Error al arrancar el cliente: {e}")
