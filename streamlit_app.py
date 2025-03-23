import streamlit as st
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from shapely.geometry import mapping
import numpy as np
import plotly.graph_objs as go
import tempfile, os, zipfile

# Imports para PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader

# Função para extrair shapefile enviado em ZIP
def extract_shapefile(zip_file):
    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(zip_file, 'r') as z:
        z.extractall(temp_dir)
    # Procura o arquivo .shp no diretório temporário
    for file in os.listdir(temp_dir):
        if file.endswith('.shp'):
            return os.path.join(temp_dir, file)
    return None

# Função para carregar shapefile e selecionar geometria (aqui simplificada para usar o primeiro registro)
def carregar_shapefile(shapefile_path):
    gdf = gpd.read_file(shapefile_path)
    if gdf.empty or 'geometry' not in gdf.columns:
        st.error("Shapefile inválido ou sem geometria.")
        return None, None
    # Se houver mais de uma geometria, lista as opções
    if len(gdf) > 1:
        opcoes = [f"Geometria {i}" for i in range(len(gdf))]
        selecionada = st.selectbox("Selecione a geometria para o recorte:", opcoes)
        index = int(selecionada.split()[1])
        geometria = gdf.geometry.iloc[index]
    else:
        geometria = gdf.geometry.iloc[0]
    return gdf, geometria

# Função para processar um raster
def calcular_volume_raster(raster_path, geometria, gdf_crs):
    with rasterio.open(raster_path) as src:
        if src.crs != gdf_crs:
            st.warning("CRS do raster e do shapefile são diferentes!")
        recorte, _ = mask(src, [mapping(geometria)], crop=True)
        meta = src.meta
    elev = recorte[0]
    if np.count_nonzero(elev) == 0:
        st.warning(f"O polígono não sobrepõe área válida em {raster_path}.")
        return None
    resolucao_x = meta['transform'][0]
    resolucao_y = abs(meta['transform'][4])
    volume = np.nansum(np.maximum(elev, 0)) * resolucao_x * resolucao_y
    area = np.count_nonzero(elev) * resolucao_x * resolucao_y
    return volume, elev, area

# Função para gerar gráficos Plotly
def gerar_graficos(elevacao):
    x = np.arange(elevacao.shape[1])
    y = np.arange(elevacao.shape[0])
    x, y = np.meshgrid(x, y)
    fig3d = go.Figure(data=[go.Surface(z=elevacao, x=x, y=y, colorscale='Viridis')])
    fig3d.update_layout(title="Modelo Digital de Elevação (3D)", scene=dict(
        xaxis_title='X (m)',
        yaxis_title='Y (m)',
        zaxis_title='Elevação (m)'
    ))
    return fig3d

# Função para gerar PDF
def gerar_pdf(relatorio_info, pdf_filename, logo_path=None, fig3d=None, fig_bar=None):
    doc = SimpleDocTemplate(pdf_filename, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    if logo_path:
        try:
            img_reader = ImageReader(logo_path)
            iw, ih = img_reader.getSize()
            max_width = 2 * inch
            max_height = 2 * inch
            ratio = min(max_width/iw, max_height/ih)
            width = iw * ratio
            height = ih * ratio
            elements.append(RLImage(logo_path, width=width, height=height))
        except Exception as e:
            st.error(f"Erro ao inserir a logo: {e}")

    elements.append(Paragraph("Relatório de Resultados - Calculadora de MDE", styles["Title"]))
    elements.append(Spacer(1, 12))
    
    metodo = ("Método: Soma das elevações não negativas multiplicada pela resolução espacial. "
              "A área é calculada como o número de pixels válidos vezes a área de cada pixel.")
    elements.append(Paragraph(metodo, styles["BodyText"]))
    elements.append(Spacer(1, 12))
    
    # Informações gerais
    info = (f"<b>Raster:</b> {relatorio_info['raster']}<br/>"
            f"<b>Volume:</b> {relatorio_info['volume']:.2f} m³<br/>"
            f"<b>Área:</b> {relatorio_info['area']:.2f} m²")
    elements.append(Paragraph(info, styles["BodyText"]))
    elements.append(Spacer(1, 12))
    
    # Tabela (para este exemplo, só um modelo)
    data = [["Raster", "Volume (m³)", "Área (m²)"],
            [relatorio_info['raster'], f"{relatorio_info['volume']:.2f}", f"{relatorio_info['area']:.2f}"]]
    table = Table(data, colWidths=[250, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.gray),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)
    elements.append(Spacer(1, 12))
    
    # Inserir imagens dos gráficos se disponíveis
    if fig3d:
        # Exporta a figura 3D para um arquivo temporário
        temp_img3d = os.path.join(tempfile.gettempdir(), "fig3d.png")
        fig3d.write_image(temp_img3d, scale=2)
        elements.append(Paragraph("Gráfico - Visualização 3D", styles["Heading2"]))
        elements.append(RLImage(temp_img3d, width=5*inch, height=3.5*inch))
        elements.append(Spacer(1, 12))
    if fig_bar:
        temp_img_bar = os.path.join(tempfile.gettempdir(), "fig_bar.png")
        fig_bar.write_image(temp_img_bar, scale=2)
        elements.append(Paragraph("Gráfico - Comparação de Volumes", styles["Heading2"]))
        elements.append(RLImage(temp_img_bar, width=5*inch, height=3.5*inch))
        elements.append(Spacer(1, 12))
    
    doc.build(elements)

# --- Streamlit App ---
st.title("Calculadora de MDE via Streamlit")

st.sidebar.header("Carregamento de Arquivos")

# Upload do shapefile (zip)
uploaded_zip = st.sidebar.file_uploader("Carregar ZIP do Shapefile", type=["zip"])
if uploaded_zip:
    shapefile_path = extract_shapefile(uploaded_zip)
    if shapefile_path:
        st.success("Shapefile extraído com sucesso!")
        gdf, geometria = carregar_shapefile(shapefile_path)
    else:
        st.error("Não foi possível encontrar o arquivo .shp no ZIP.")

# Upload de rasters
uploaded_rasters = st.sidebar.file_uploader("Carregar Raster(s) (GeoTIFF)", type=["tif"], accept_multiple_files=True)

if st.sidebar.button("Processar MDE"):
    if not uploaded_zip:
        st.error("Carregue o shapefile (ZIP) primeiro!")
    elif not uploaded_rasters:
        st.error("Carregue pelo menos um raster!")
    else:
        resultados = []
        for raster_file in uploaded_rasters:
            # Salva o raster temporariamente
            temp_raster = os.path.join(tempfile.gettempdir(), raster_file.name)
            with open(temp_raster, "wb") as f:
                f.write(raster_file.getbuffer())
            resultado = calcular_volume_raster(temp_raster, geometria, gdf.crs)
            if resultado:
                resultados.append((raster_file.name, *resultado))
        if resultados:
            st.success("Processamento concluído!")
            # Exibe os resultados
            for nome, volume, elevacao, area in resultados:
                st.write(f"**Raster:** {nome}")
                st.write(f"Volume: {volume:.2f} m³ | Área: {area:.2f} m²")
                fig3d = gerar_graficos(elevacao)
                st.plotly_chart(fig3d)
            # Para exemplo, usa o primeiro resultado para o PDF
            relatorio_info = {
                "raster": resultados[0][0],
                "volume": resultados[0][1],
                "area": resultados[0][3]
            }
            # Exibe botões para gerar PDF
            if st.button("Gerar PDF dos Resultados"):
                logo_file = st.sidebar.file_uploader("Carregar Logo (opcional)", type=["png", "jpg", "jpeg"])
                # Salva a logo se enviada
                logo_path = None
                if logo_file:
                    logo_path = os.path.join(tempfile.gettempdir(), logo_file.name)
                    with open(logo_path, "wb") as f:
                        f.write(logo_file.getbuffer())
                # Exemplo: gera também um gráfico de barras simples com os volumes de todos os rasters
                modelos = [r[0] for r in resultados]
                volumes = [r[1] for r in resultados]
                fig_bar = go.Figure(data=[go.Bar(x=modelos, y=volumes)])
                fig_bar.update_layout(title="Comparação de Volumes", xaxis_title="Modelo", yaxis_title="Volume (m³)")
                # Define caminho para salvar o PDF
                pdf_filename = os.path.join(tempfile.gettempdir(), "Relatorio_MDE.pdf")
                gerar_pdf(relatorio_info, pdf_filename, logo_path, fig3d, fig_bar)
                st.success("PDF gerado com sucesso!")
                with open(pdf_filename, "rb") as f:
                    st.download_button("Baixar PDF", f, file_name="Relatorio_MDE.pdf")
