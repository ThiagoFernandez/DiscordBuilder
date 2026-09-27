import os
import sys
import discord
import json
import argparse
from dotenv import load_dotenv

parser = argparse.ArgumentParser(description="Arma un servidor de Discord desde un JSON.")
parser.add_argument("--dry-run", action="store_true", help="Imprime el plan sin tocar el servidor.")
args = parser.parse_args()

def get_server_config():
    with open("server.json", "r", encoding="utf-8") as f:
        return json.load(f)

def validar_json(config):
    """Valida la estructura del JSON antes de conectar el bot a Discord."""
    for i, rol in enumerate(config.get("roles", [])):
        if "name" not in rol:
            raise ValueError(f"Falta 'name' en el rol #{i+1}")

    for i, cat in enumerate(config.get("categories", [])):
        if "name" not in cat:
            raise ValueError(f"Falta 'name' en la categoría #{i+1}")

        for j, canal in enumerate(cat.get("channels", [])):
            if "name" not in canal:
                raise ValueError(f"Falta 'name' en un canal de la categoría '{cat['name']}'")
            if canal.get("type") not in ["text", "voice"]:
                raise ValueError(f"El canal '{canal.get('name')}' tiene un type inválido. Usa 'text' o 'voice'.")

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

            if rol_existente:
                if args.dry_run:
                    print(f" [DRY-RUN] Actualizaría el rol '{nombre_rol}'.")
                else:
                    await rol_existente.edit(hoist=is_hoist, colour=discord.Colour(color_val))
                    print(f" - Rol '{nombre_rol}' ya existe (color/hoist actualizados).")
            else:
                if args.dry_run:
                    print(f" [DRY-RUN] Crearía el rol '{nombre_rol}'.")
                else:
                    await guild.create_role(
                        name=nombre_rol,
                        hoist=is_hoist,
                        colour=discord.Colour(color_val)
                    )
                    print(f" ✅ Rol '{nombre_rol}' creado (hoist={is_hoist}, color={color_val}).")

        print("\n⚙️ Procesando Categorías y Canales...")
        for cat_data in config.get("categories", []):
            nombre_cat = cat_data["name"]

            overwrites_dict = {}
            if "overwrites" in cat_data:
                for rol_nombre, permisos in cat_data["overwrites"].items():
                    if rol_nombre == "@everyone":
                        rol_obj = guild.default_role
                    else:
                        rol_obj = discord.utils.get(guild.roles, name=rol_nombre)

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

                if tipo == "text":
                    nombre_esperado = nombre_canal.lower().replace(" ", "-")
                    canal_existente = discord.utils.get(canales_en_categoria, name=nombre_esperado)

                    if not canal_existente:
                        if args.dry_run:
                            print(f"   💬 [DRY-RUN] Crearía canal de texto '{nombre_canal}'.")
                        else:
                            topic = canal_data.get("topic")
                            await guild.create_text_channel(name=nombre_canal, category=cat_existente, topic=topic)
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
                                user_limit=limite_usuarios
                            )
                            print(f"   🔊 Canal de voz '{nombre_canal}' creado.")
                    else:
                        print(f"   - Canal de voz '{nombre_esperado}' ya existe.")

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
